# Tauri Lifecycle & Sidecar Management
You are implementing the Rust backend for a Tauri application.
1. The app relies on a Python executable configured as a Tauri Sidecar.
2. The Sidecar MUST be spawned upon application initialization.
3. You must implement OS-level hooks to ensure that when the Tauri window is closed, the Python Sidecar process is explicitly terminated. No orphaned processes can remain. 
4. The launch sequence will require elevated privileges (UAC) on Windows to execute the Python script's credential broker. Ensure Tauri's configuration allows for this elevation.
