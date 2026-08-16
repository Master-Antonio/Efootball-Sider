import os
import sys
from pathlib import Path

root_dir = str(Path(__file__).resolve().parents[1])
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    pages = [win._nav_group.button(i).text() for i in range(len(win._nav_group.buttons()))]
    print("=== SIDER STUDIO GUI VERIFICATION SUCCESS ===")
    print("Loaded Navigation Pages:", pages)
    print("Total Stacked Pages:", win._stack.count())
    print("ZenBuilder available:", win.context.zen_builder.is_available())
    print("Database Service ready:", win.context.database is not None)
    print("Memory Discovery ready:", win.context.memory is not None)

if __name__ == "__main__":
    main()
