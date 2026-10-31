"""桌面工作台（PySide6 + NodeGraphQt）。"""

import os

# NodeGraphQt 经 Qt.py 选择 Qt 绑定，须在首次导入 NodeGraphQt 之前设定
os.environ.setdefault("QT_PREFERRED_BINDING", "PySide6")
