# IPC (Inter-Process Communication) Bridge
1. The frontend React application must communicate with the Python sidecar via Tauri's IPC system (Commands).
2. To update a transaction category, the frontend will invoke a Tauri command with `transaction_id` and `new_category_id`.
3. Tauri will pass these arguments to the running Python sidecar via standard input (`stdin`) or a local lightweight socket, depending on the established Sidecar communication pattern.
4. The Python script will execute the `UPDATE` query on the local SQL database and return a success/fail boolean back through Tauri to the frontend.
