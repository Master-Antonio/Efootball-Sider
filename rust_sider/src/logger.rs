use chrono::Local;
use std::fs::OpenOptions;
use std::io::{BufWriter, Write};
use std::path::PathBuf;
use std::sync::mpsc::{channel, Receiver, Sender, TryRecvError};
use std::sync::OnceLock;
use std::thread;

const BUFFER_CAPACITY: usize = 64 * 1024;
static LOG_SENDER: OnceLock<Sender<String>> = OnceLock::new();
static MODULE_HANDLE: OnceLock<isize> = OnceLock::new();

/// Registers the SIDER DLL module handle so the log can be anchored to an
/// absolute path (the game may change its CWD at runtime).
pub fn set_module_handle(handle: isize) {
    let _ = MODULE_HANDLE.set(handle);
}

/// Directory containing the SIDER DLL (absolute, CWD-independent).
pub fn dll_dir() -> PathBuf {
    if let Some(handle) = MODULE_HANDLE.get() {
        let mut buffer = [0u16; 1024];
        let len = unsafe {
            windows_sys::Win32::System::LibraryLoader::GetModuleFileNameW(
                *handle as windows_sys::Win32::Foundation::HMODULE,
                buffer.as_mut_ptr(),
                buffer.len() as u32,
            )
        };
        if len > 0 {
            let s = String::from_utf16_lossy(&buffer[..len as usize]);
            if let Some(parent) = PathBuf::from(s).parent() {
                return parent.to_path_buf();
            }
        }
    }
    PathBuf::from(".")
}

fn log_path() -> PathBuf {
    dll_dir().join("sider_rust.log")
}

fn init_logger() -> Sender<String> {
    let (tx, rx) = channel::<String>();
    thread::Builder::new()
        .name("sider_async_logger".to_string())
        .spawn(move || {
            logger_worker(rx);
        })
        .expect("Impossibile avviare il thread di logging asincrono");
    tx
}

fn logger_worker(rx: Receiver<String>) {
    let file = match OpenOptions::new().create(true).append(true).open(log_path()) {
        Ok(f) => f,
        Err(_) => return,
    };

    let mut writer = BufWriter::with_capacity(BUFFER_CAPACITY, file);

    while let Ok(msg) = rx.recv() {
        let timestamp = Local::now().format("%Y-%m-%d %H:%M:%S%.3f");
        let _ = writeln!(writer, "[{}][SIDER] {}", timestamp, msg);
        let _ = writer.flush();

        loop {
            match rx.try_recv() {
                Ok(next_msg) => {
                    let ts = Local::now().format("%Y-%m-%d %H:%M:%S%.3f");
                    let _ = writeln!(writer, "[{}][SIDER] {}", ts, next_msg);
                    let _ = writer.flush();
                }
                Err(TryRecvError::Empty) => {
                    let _ = writer.flush();
                    break;
                }
                Err(TryRecvError::Disconnected) => {
                    let _ = writer.flush();
                    return;
                }
            }
        }
    }
    let _ = writer.flush();
}

pub fn log_async(msg: &str) {
    let tx = LOG_SENDER.get_or_init(init_logger);
    let _ = tx.send(msg.to_string());
}
