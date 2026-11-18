#include <iostream>
#include <string>
#include <windows.h>

#define IOCTL_HIDE_PROCESS CTL_CODE(FILE_DEVICE_UNKNOWN, 0x800, METHOD_BUFFERED, FILE_ANY_ACCESS)

int main(int argc, char* argv[])
{
    if (argc != 2)
    {
        std::cerr << "Usage: " << argv[0] << " <process_name>" << std::endl;
        return 1;
    }

    std::string procName = argv[1];

    HANDLE hDevice = CreateFileW(
        L"\\\\.\\HideProcess",
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        NULL,
        OPEN_EXISTING,
        0,
        NULL
    );

    if (hDevice == INVALID_HANDLE_VALUE)
    {
        std::cerr << "Failed to open device, error: " << GetLastError() << std::endl;
        return 1;
    }

    DWORD bytesReturned;
    BOOL result = DeviceIoControl(
        hDevice,
        IOCTL_HIDE_PROCESS,
        (LPVOID)procName.c_str(),
        (DWORD)(procName.length() + 1),
        NULL,
        0,
        &bytesReturned,
        NULL
    );

    if (result)
    {
        std::cout << "Process name sent successfully: " << procName << std::endl;
    }
    else
    {
        std::cerr << "Failed to send process name. Error: " << GetLastError() << std::endl;
    }

    CloseHandle(hDevice);
    return result ? 0 : 1;
}
