#pragma once

#include <ntddk.h>

// Globals resolved at driver load time.
extern ULONG g_PidOffset;
extern ULONG g_NameOffset;
extern ULONG g_ListEntryOffset;

// Offset resolution routines.
BOOLEAN InitializeOffsets(void);

// Hide a process by name via DKOM unlinking of ActiveProcessLinks.
VOID HideProcessByName(_In_z_ const char* target);
