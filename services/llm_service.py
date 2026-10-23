import orjson
import asyncio
import time
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from openai import AsyncOpenAI, APIStatusError
from core.config import settings
from core.key_utils import usable_keys
from core.prompts import get_interview_answer_prompt, get_quick_response_prompt
from core.retry_utils import is_rate_limit_error, cooldown_seconds
from services.context_manager import PersistentContextManager
import threading

# --- Enhanced LLMManager Class ---

class LLMManager:
    """Enhanced LLM Manager with persistent context support and error recovery."""
    
    def __init__(self, provider_name: str, base_url: str, api_key: str, model_name: str, request_params: Optional[Dict[str, Any]] = None, api_keys: Optional[List[str]] = None):
        self.provider_name = provider_name
        self.model_name = model_name
        self.base_url = base_url
        self.request_params = request_params or {}
        self.context_manager = None  # Will be shared from MultiLLMManager
        self.is_healthy = True
        self.last_error = None
        self.error_count = 0
        self.last_success_time = datetime.now()
        
        # Key rotation support — drop blank/placeholder entries so a half-filled
        # config (real "apiKey" + untouched "apiKeys" placeholders) still works.
        self.api_keys = usable_keys(api_keys) or usable_keys([api_key]) or [""]
        if not self.api_keys[0]:
            print(f"⚠️ No usable API key for {provider_name} — set 'apiKey' or 'apiKeys' in ai_providers.json")
        self.api_key = self.api_keys[0]  # Current active key
        self._key_index = 0
        self._key_lock = threading.Lock()
        self._request_count = 0
        # key index -> monotonic time until which the key should be skipped
        self._key_cooldowns: Dict[int, float] = {}
        
        try:
            self.client = AsyncOpenAI(base_url=base_url, api_key=self.api_key)
            print(f"✅ LLMManager initialized for: {self.provider_name} - {self.model_name} ({len(self.api_keys)} keys available)")
        except Exception as e:
            self.client = None
            self.is_healthy = False
            self.last_error = str(e)
            print(f"❌ CRITICAL: Failed to initialize LLMManager for {self.provider_name}: {e}")

    def _rotate_key(self):
        """Rotate to the next API key using round-robin."""
        if len(self.api_keys) <= 1:
            return
        with self._key_lock:
            self._key_index = (self._key_index + 1) % len(self.api_keys)
            self.api_key = self.api_keys[self._key_index]
            self.client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
            self._request_count += 1
            print(f"🔑 Key rotation [{self.provider_name}]: using key index {self._key_index}/{len(self.api_keys)}")

    def _activate_key(self, index: int):
        """Switch to a specific key index and rebuild the client for it."""
        if index == self._key_index and self.client is not None:
            return
        with self._key_lock:
            self._key_index = index
            self.api_key = self.api_keys[index]
            self.client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)

    def _next_available_key_index(self) -> int:
        """Next key index (round-robin) that is not currently cooling down."""
        now = time.monotonic()
        count = len(self.api_keys)
        for offset in range(1, count + 1):
            candidate = (self._key_index + offset) % count
            if self._key_cooldowns.get(candidate, 0.0) <= now:
                return candidate
        # Every key is cooling down; still return the next one.
        return (self._key_index + 1) % count

    def has_available_key(self) -> bool:
        """True when at least one key is not currently rate-limited."""
        now = time.monotonic()
        return any(self._key_cooldowns.get(i, 0.0) <= now for i in range(len(self.api_keys)))

    def _cool_down_current_key(self, exc: Exception, attempt: int):
        wait = cooldown_seconds(exc, attempt)
        self._key_cooldowns[self._key_index] = time.monotonic() + wait
        print(f"⏳ Rate limited [{self.provider_name}/{self.model_name}] key #{self._key_index} — skipping for {wait:.1f}s")

    def set_context_manager(self, context_manager: PersistentContextManager):
        """Set the shared context manager"""
        self.context_manager = context_manager

    async def health_check(self) -> bool:
        """Check if the provider is healthy and responsive"""
        if not self.client:
            return False
            
        try:
            # Quick test call to verify connectivity
            await asyncio.wait_for(self.client.models.list(), timeout=5.0)
            self.is_healthy = True
            self.error_count = 0
            self.last_success_time = datetime.now()
            return True
        except asyncio.TimeoutError:
            self.is_healthy = False
            self.last_error = "Connection timeout"
            self.error_count += 1
            return False
        except Exception as e:
            self.is_healthy = False
            self.last_error = str(e)
            self.error_count += 1
            return False

    async def get_ai_answer(self, question: str, stream_callback=None, response_style: str = None,
                            add_to_context: bool = True) -> Tuple[str, Dict[str, Any]]:
        """Get an AI answer, rotating keys and skipping rate-limited ones.

        ``add_to_context`` is False when the caller (MultiLLMManager) has already
        recorded the question once, so provider/model fallbacks do not create
        duplicate conversation entries.
        """
        if not self.client:
            return "I'm sorry, the AI service is not available at this time.", {
                "error": "No client available",
                "provider": self.provider_name,
                "model": self.model_name
            }

        if not self.context_manager or not self.context_manager.ensure_context_available():
            return "I'm sorry, candidate context is not properly initialized.", {
                "error": "Context not available",
                "provider": self.provider_name,
                "model": self.model_name
            }

        # Add question to conversation history (once, before retry loop)
        if add_to_context:
            self.context_manager.add_conversation_exchange(question)

        # Generate prompt with persistent context.
        # GENERATE_FULL_ANSWERS=false routes to the short-form prompt.
        if settings.GENERATE_FULL_ANSWERS:
            prompt = get_interview_answer_prompt(question, self.context_manager, response_style=response_style)
        else:
            prompt = get_quick_response_prompt(question, self.context_manager)

        print(f"🎯 Processing with {self.provider_name}-{self.model_name}: '{question[:100]}...'")

        # Proactive round-robin: start every request on the next available key so
        # multiple keys (e.g. several Gemini keys) share rate limits evenly.
        if len(self.api_keys) > 1:
            self._activate_key(self._next_available_key_index())

        # Try all available keys. Rate-limited keys are put on cooldown and
        # skipped; if every key is cooling down the call fails fast so the
        # caller can fall back to another model/provider instead of sleeping.
        max_attempts = max(len(self.api_keys), 1)
        last_error = None
        rate_limited = False

        for attempt in range(max_attempts):
            try:
                # Build API params
                api_params = {
                    "messages": [{"role": "user", "content": prompt}],
                    "model": self.model_name,
                    "temperature": 0.3,
                    "top_p": 0.85,
                    "max_tokens": 8000
                }

                # Add provider-specific routing if available
                if self.request_params:
                    if self.provider_name == "OpenRouter" and "provider" in self.request_params:
                        api_params["extra_body"] = self.request_params
                    else:
                        api_params.update(self.request_params)

                # Determine if streaming is requested
                use_streaming = stream_callback is not None

                if use_streaming:
                    api_params["stream"] = True
                    full_answer = ""
                    streaming_active = True
                    try:
                        async for chunk in await self.client.chat.completions.create(**api_params):
                            if not streaming_active:
                                break

                            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                                content_chunk = chunk.choices[0].delta.content
                                full_answer += content_chunk
                                if stream_callback:
                                    try:
                                        callback_result = await stream_callback(content_chunk, "chunk")
                                        if callback_result is False:
                                            streaming_active = False
                                            break
                                    except Exception as e:
                                        streaming_active = False
                                        break
                        answer = full_answer.strip()

                    except Exception as stream_err:
                        print(f"⚠️ Streaming failed for {self.provider_name} key #{self._key_index}: {stream_err}")
                        raise stream_err  # Let the outer retry loop handle it
                else:
                    # Non-streaming API call
                    chat_completion = await asyncio.wait_for(
                        self.client.chat.completions.create(**api_params),
                        timeout=30.0
                    )
                    answer = chat_completion.choices[0].message.content.strip()

                # Success! Add AI response and return
                self.context_manager.add_ai_response(answer, "normal")
                self.is_healthy = True
                self.error_count = 0
                self.last_success_time = datetime.now()

                return answer, {
                    "success": True,
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "key_rotated": attempt > 0,
                    "attempt": attempt + 1,
                    "response_time": datetime.now().isoformat()
                }

            except Exception as e:
                last_error = e
                err_str = str(e)[:100]
                if is_rate_limit_error(e):
                    rate_limited = True
                    self._cool_down_current_key(e, attempt + 1)
                print(f"⚡ Key #{self._key_index} failed for {self.provider_name}: {err_str}")
                # Try the next available key immediately.
                if attempt + 1 < max_attempts and len(self.api_keys) > 1:
                    self._activate_key(self._next_available_key_index())
                continue

        # All keys exhausted
        self.is_healthy = False
        self.last_error = str(last_error)
        self.error_count += 1
        if rate_limited:
            error_msg = (f"Rate limit reached for {self.provider_name} ({self.model_name}). "
                         f"All {max_attempts} key(s) are cooling down.")
            print(f"⏳ ALL KEYS RATE LIMITED: {self.provider_name}-{self.model_name}")
        else:
            error_msg = f"All {max_attempts} keys failed for {self.provider_name}. Last error: {str(last_error)[:100]}"
            print(f"🚨 ALL KEYS EXHAUSTED: {self.provider_name}-{self.model_name}")

        return error_msg, {
            "success": False,
            "error": "all_keys_failed",
            "rate_limited": rate_limited,
            "attempts": max_attempts,
            "provider": self.provider_name,
            "model": self.model_name
        }

    def process_candidate_response(self, response: str):
        """Processes the candidate's response to add to conversation context."""
        if settings.TRACK_CANDIDATE_RESPONSES and response.strip() and self.context_manager:
            self.context_manager.add_conversation_exchange(None, response)
            print("📝 Conversation context updated with candidate response")

    def get_status(self) -> Dict[str, Any]:
        """Get current status of this LLM manager"""
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "is_healthy": self.is_healthy,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "last_success": self.last_success_time.isoformat() if self.last_success_time else None
        }

# --- Multi-LLM Manager Class ---

class MultiLLMManager:
    """Enhanced LLM Manager supporting multiple providers with shared context and comprehensive error handling"""
    
    def __init__(self):
        self.providers: Dict[str, LLMManager] = {}
        self.presets: Dict[str, Dict[str, str]] = {}
        self.active_preset_key = "primary"
        self.shared_context = PersistentContextManager()
        self.fallback_order = ["primary", "secondary", "auto"]
        self.auto_switch_enabled = True
        self.health_check_interval = 300  # 5 minutes
        self.last_health_check = None
        # Per-preset alternate models of the same provider. Used when the
        # selected model is rate-limited (e.g. Gemini 3.8 Flash's low RPD).
        self.model_fallbacks: Dict[str, List[LLMManager]] = {}
        self._provider_configs: Dict[str, Dict[str, Any]] = {}
        
    def load_configuration(self, primary_config: Dict[str, str], secondary_config: Optional[Dict[str, str]] = None):
        """Load primary and optional secondary configurations"""
        try:
            # Load providers from JSON using high-performance orjson
            with open("ai_providers.json", "rb") as f:
                providers_config = orjson.loads(f.read())

            self._provider_configs = {
                p["name"]: p for p in providers_config if isinstance(p, dict) and p.get("name")
            }

            # Setup primary provider
            primary_provider_config = next((p for p in providers_config
                                          if p["name"] == primary_config["provider"]), None)
            
            if not primary_provider_config:
                raise ValueError(f"Primary provider '{primary_config['provider']}' not found in configuration")

            secondary_provider_config = None
            
            # --- Primary Provider Setup ---
            primary_model_config = self._get_model_config(primary_provider_config, primary_config["model"])
            
            self.presets["primary"] = {
                "provider": primary_config["provider"],
                "model": primary_model_config["modelName"],
                "description": primary_model_config.get("description", f"Primary - {primary_config['provider']} ({primary_model_config['modelName']})"),
                "priority": 1
            }

            self.providers["primary"] = LLMManager(
                provider_name=primary_provider_config["name"],
                base_url=primary_provider_config["baseURL"],
                api_key=primary_provider_config.get("apiKey", ""),
                model_name=primary_model_config["modelName"],
                request_params=primary_model_config.get("requestParams"),
                api_keys=primary_provider_config.get("apiKeys")
            )
            self.providers["primary"].set_context_manager(self.shared_context)
            
            # Setup secondary provider if provided
            if secondary_config and secondary_config.get("provider") and secondary_config.get("model"):
                secondary_provider_config = next((p for p in providers_config
                                                if p["name"] == secondary_config["provider"]), None)
                
                if secondary_provider_config:
                    secondary_model_config = self._get_model_config(secondary_provider_config, secondary_config["model"])
                    
                    self.presets["secondary"] = {
                        "provider": secondary_config["provider"],
                        "model": secondary_model_config["modelName"],
                        "description": secondary_model_config.get("description", f"Secondary - {secondary_config['provider']} ({secondary_model_config['modelName']})"),
                        "priority": 2
                    }
                    
                    self.providers["secondary"] = LLMManager(
                        provider_name=secondary_provider_config["name"],
                        base_url=secondary_provider_config["baseURL"],
                        api_key=secondary_provider_config.get("apiKey", ""),
                        model_name=secondary_model_config["modelName"],
                        request_params=secondary_model_config.get("requestParams"),
                        api_keys=secondary_provider_config.get("apiKeys")
                    )
                    self.providers["secondary"].set_context_manager(self.shared_context)
                    
                    # Update fallback order
                    self.fallback_order = ["primary", "secondary"]
                else:
                    print(f"⚠️ WARNING: Secondary provider '{secondary_config['provider']}' not found in configuration")
            
            # Setup auto-select preset
            self.presets["auto"] = {
                "provider": "Auto-Select",
                "model": "Best Available",
                "description": "Auto-Select Best Available Model",
                "priority": 0
            }

            # Build alternate-model fallbacks for each configured preset so a
            # rate-limited model (low RPD) can fail over within its provider.
            self.model_fallbacks = {}
            if "primary" in self.providers:
                self.model_fallbacks["primary"] = self._build_model_fallbacks(
                    primary_provider_config, self.providers["primary"].model_name
                )
            if "secondary" in self.providers and secondary_provider_config:
                self.model_fallbacks["secondary"] = self._build_model_fallbacks(
                    secondary_provider_config, self.providers["secondary"].model_name
                )

            print(f"✅ MultiLLMManager initialized with {len(self.providers)} providers")
            print(f"   📋 Available presets: {list(self.presets.keys())}")
            
            return True
            
        except Exception as e:
            print(f"❌ CRITICAL: Failed to load MultiLLMManager configuration: {e}")
            return False

    def _get_model_config(self, provider_config: Dict[str, Any], model_identifier: str) -> Dict[str, Any]:
        """Finds model configuration, supporting both string and dict formats."""
        for model in provider_config.get("models", []):
            if isinstance(model, str) and model == model_identifier:
                return {"modelName": model} # Normalize to dict
            if isinstance(model, dict) and model.get("modelName") == model_identifier:
                return model
        raise ValueError(f"Model '{model_identifier}' not found for provider '{provider_config['name']}'")

    def _build_model_fallbacks(self, provider_config: Dict[str, Any], current_model: str) -> List[LLMManager]:
        """Create managers for every other model of the same provider.

        The order follows ``models`` in ai_providers.json (flagship first, then
        lighter/higher-quota models), which is exactly what we want when the
        selected model runs out of requests.
        """
        managers: List[LLMManager] = []
        seen = {current_model}
        for model in provider_config.get("models", []):
            if isinstance(model, dict):
                model_name = model.get("modelName")
                request_params = model.get("requestParams")
            else:
                model_name = model
                request_params = None
            if not model_name or model_name in seen:
                continue
            seen.add(model_name)
            try:
                manager = LLMManager(
                    provider_name=provider_config["name"],
                    base_url=provider_config["baseURL"],
                    api_key=provider_config.get("apiKey", ""),
                    model_name=model_name,
                    request_params=request_params,
                    api_keys=provider_config.get("apiKeys")
                )
                manager.set_context_manager(self.shared_context)
                managers.append(manager)
            except Exception as e:
                print(f"⚠️ Could not build fallback model '{model_name}': {e}")
        if managers:
            print(f"🧩 {provider_config['name']}: {len(managers)} fallback model(s) available")
        return managers

    def initialize_candidate_context(self, onboarding_data: Dict[str, Any]):
        """Initialize shared candidate context"""
        self.shared_context.initialize_persistent_context(onboarding_data)
        print(f"🔒 Shared context initialized for candidate: {onboarding_data.get('name', 'Unknown')}")

    async def perform_health_checks(self) -> Dict[str, bool]:
        """Perform health checks on all providers"""
        health_results = {}
        
        for preset_key, manager in self.providers.items():
            try:
                is_healthy = await manager.health_check()
                health_results[preset_key] = is_healthy
                status = "✅ Healthy" if is_healthy else f"❌ Unhealthy: {manager.last_error}"
                print(f"🏥 Health check {preset_key}: {status}")
            except Exception as e:
                health_results[preset_key] = False
                print(f"🏥 Health check {preset_key}: ❌ Failed - {e}")
        
        self.last_health_check = datetime.now()
        return health_results

    async def switch_preset(self, preset_key: str) -> Tuple[bool, Dict[str, Any]]:
        """Switch to a different preset with validation"""
        if preset_key == "auto":
            # Auto-select the best available provider
            return await self.auto_select_best_provider()
        
        if preset_key not in self.providers:
            error_msg = f"Preset '{preset_key}' not available"
            print(f"❌ {error_msg}")
            return False, {"error": error_msg, "available_presets": list(self.presets.keys())}
        
        # Check if the provider is healthy
        manager = self.providers[preset_key]
        if not manager.is_healthy:
            print(f"⚠️ WARNING: Switching to unhealthy provider {preset_key}")
        
        old_preset = self.active_preset_key
        self.active_preset_key = preset_key
        
        preset_info = self.get_current_preset_info()
        print(f"🔄 Switched from {old_preset} to {preset_key} ({preset_info['description']})")
        
        return True, {
            "success": True,
            "previous_preset": old_preset,
            "current_preset": preset_info
        }

    async def auto_select_best_provider(self) -> Tuple[bool, Dict[str, Any]]:
        """Automatically select the best available provider based on health"""
        print("🤖 Auto-selecting best available provider...")
        
        # Perform health checks
        health_results = await self.perform_health_checks()
        
        # Find the best healthy provider in priority order
        for preset_key in self.fallback_order:
            if preset_key in health_results and health_results[preset_key]:
                old_preset = self.active_preset_key
                self.active_preset_key = preset_key
                
                preset_info = self.get_current_preset_info()
                print(f"🎯 Auto-selected {preset_key} as the best available provider")
                
                return True, {
                    "success": True,
                    "auto_selected": True,
                    "previous_preset": old_preset,
                    "current_preset": preset_info,
                    "health_results": health_results
                }
        
        # No healthy providers found
        error_msg = "No healthy providers available"
        print(f"🚨 CRITICAL: {error_msg}")
        return False, {
            "error": error_msg,
            "health_results": health_results
        }

    def get_current_preset_info(self) -> Dict[str, Any]:
        """Get info about currently active preset"""
        if self.active_preset_key in self.presets:
            preset = self.presets[self.active_preset_key]
            manager = self.providers.get(self.active_preset_key)
            
            return {
                "key": self.active_preset_key,
                "provider": preset["provider"],
                "model": preset["model"],
                "description": preset["description"],
                "priority": preset["priority"],
                "is_healthy": manager.is_healthy if manager else False,
                "status": manager.get_status() if manager else None
            }
        return {"key": "unknown", "provider": "Unknown", "model": "Unknown", "description": "Unknown"}

    async def get_ai_answer(self, question: str, stream_callback=None, response_style: str = None) -> Tuple[str, Dict[str, Any]]:
        """Generate an answer with provider and model-level fallback.

        Order: the active preset's model, that provider's alternate models, the
        other configured preset, then its alternate models. Streaming is only
        used for the very first attempt so a fallback answer is never merged
        into partial output from a failed stream.
        """
        if not self.providers:
            return "No AI providers are configured.", {"error": "no_providers"}

        # Record the question once, so provider/model fallbacks do not each add
        # a duplicate conversation entry.
        if self.shared_context and self.shared_context.ensure_context_available():
            self.shared_context.add_conversation_exchange(question)

        preset_order = []
        if self.active_preset_key in self.providers:
            preset_order.append(self.active_preset_key)
        preset_order.extend(
            preset for preset in self.fallback_order
            if preset != self.active_preset_key and preset in self.providers
        )
        if not preset_order:
            preset_order = list(self.providers.keys())

        original_preset = self.active_preset_key
        stream_used = False
        saw_rate_limit = False

        for preset_key in preset_order:
            manager = self.providers[preset_key]

            # Build the attempt order for this preset: selected model first
            # (unless every key is cooling down), then alternate models.
            candidates: List[Tuple[LLMManager, bool]] = []
            if manager.has_available_key():
                candidates.append((manager, False))
            else:
                print(f"⏭️ Skipping {manager.provider_name}/{manager.model_name} — all keys rate limited")

            for fallback in self.model_fallbacks.get(preset_key, []):
                if fallback.has_available_key():
                    candidates.append((fallback, True))

            for candidate, is_model_fallback in candidates:
                callback = stream_callback if (not stream_used and not is_model_fallback) else None
                answer, result_info = await candidate.get_ai_answer(
                    question, callback, response_style, add_to_context=False
                )
                stream_used = True

                if result_info.get("success"):
                    self.active_preset_key = preset_key
                    info = self.get_current_preset_info()
                    if is_model_fallback:
                        info = {
                            "key": preset_key,
                            "provider": candidate.provider_name,
                            "model": candidate.model_name,
                            "description": f"{candidate.provider_name} ({candidate.model_name}) model fallback",
                            "priority": info.get("priority", 0),
                        }
                        result_info["model_fallback"] = True
                        result_info["rate_limited_primary"] = saw_rate_limit
                    result_info["preset_used"] = info
                    result_info["fallback_used"] = (preset_key != original_preset) or is_model_fallback
                    if result_info["fallback_used"]:
                        result_info["original_preset"] = original_preset
                        print(f"✅ Answer served by fallback: {candidate.provider_name}/{candidate.model_name}")
                    return answer, result_info

                reason = "rate limited" if result_info.get("rate_limited") else "failed"
                if result_info.get("rate_limited"):
                    saw_rate_limit = True
                print(f"⚠️ {candidate.provider_name}/{candidate.model_name} {reason}; trying next option...")

        # All providers and models failed
        error_msg = "All AI providers are currently unavailable. Please try again in a moment."
        return error_msg, {
            "error": "all_providers_failed",
            "rate_limited": saw_rate_limit,
            "attempted_providers": list(self.providers.keys())
        }

    def process_candidate_response(self, response: str):
        """Process candidate response using active provider"""
        if self.active_preset_key in self.providers:
            self.providers[self.active_preset_key].process_candidate_response(response)

    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        provider_statuses = {}
        for preset_key, manager in self.providers.items():
            provider_statuses[preset_key] = manager.get_status()
        
        return {
            "active_preset": self.active_preset_key,
            "available_presets": self.presets,
            "provider_statuses": provider_statuses,
            "fallback_order": self.fallback_order,
            "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
            "context_status": {
                "is_initialized": self.shared_context.is_initialized,
                "conversation_count": len(self.shared_context.conversation_history)
            }
        }

    def reset_context(self):
        """Resets the conversation context."""
        if self.shared_context:
            self.shared_context.reset_conversation_history()

# --- Standalone Verification Function ---

async def verify_provider_connection(base_url: str, api_key: str, model_name: str) -> bool:
    """Verifies a connection to an AI provider without creating a full manager instance."""
    try:
        temp_client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        await asyncio.wait_for(temp_client.models.list(), timeout=20.0)
        print(f"✅ Connection to {base_url} with model {model_name} is valid.")
        return True
    except asyncio.TimeoutError:
        print(f"⏱️ TIMEOUT: Connection to {base_url} timed out")
        return False
    except APIStatusError as e:
        print(f"❌ ERROR: API key verification failed for {base_url}. Status: {e.status_code}")
        return False
    except Exception as e:
        print(f"❌ ERROR: An unexpected error occurred during provider verification for {base_url}: {e}")
        return False