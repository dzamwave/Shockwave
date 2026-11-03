import ctypes

# Windows constants
ERROR_ALREADY_EXISTS = 183

_mutex_handle = None

def check_single_instance(mutex_name="Local\\Shockwave_App_Mutex_v093"):
    """
    Ensures only one instance of Shockwave runs at any given time
    using a native Windows Named Mutex.
    
    Returns:
        bool: True if this is the only running instance (or already acquired by this process),
              False if a duplicate running process was detected.
    """
    global _mutex_handle
    
    # If the current process has already acquired the mutex, allow continuation
    if _mutex_handle is not None:
        return True
    
    try:
        kernel32 = ctypes.windll.kernel32
        # Create or open named mutex
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        last_error = kernel32.GetLastError()
        
        if last_error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _mutex_handle = handle
        return True
    except Exception as e:
        print(f"Single instance mutex notice: {e}")
        return True

def release_single_instance():
    """Releases the mutex handle upon application termination."""
    global _mutex_handle
    if _mutex_handle is not None:
        try:
            ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        except Exception:
            pass
        _mutex_handle = None
