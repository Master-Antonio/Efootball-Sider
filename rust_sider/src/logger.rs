use chrono::Local;
use std::fs::OpenOptions;
use std::io::{BufWriter, Write};
use std::sync::mpsc::{channel, Receiver, Sender, TryRecvError};
use std::sync::OnceLock;
use std::thread;

const BUFFER_CAPACITY: usize = 64 * 1024;
static LOG_SENDER: OnceLock<Sender<String>> = OnceLock::new();

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
    let file = match OpenOptions::new()
        .create(true)
        .append(true)
        .open("sider_rust.log")
    {
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
