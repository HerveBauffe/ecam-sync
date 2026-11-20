mod devices;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(if cfg!(debug_assertions) { log::LevelFilter::Debug } else { log::LevelFilter::Info })
                .build(),
        )
        .plugin(tauri_plugin_blec::init())
        .manage(devices::Devices::default())
        .invoke_handler(tauri::generate_handler![
            devices::ble_scan,
            devices::trainer_connect,
            devices::trainer_set_power,
            devices::trainer_free_ride,
            devices::controller_connect,
            devices::ble_disconnect_all,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
