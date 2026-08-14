import os

from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QFrame, QMessageBox)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QFontMetrics
from app_paths import resource_path


USER_GUIDE_PATH = resource_path("User_guide.pdf")


class PageHelp(QWidget):
    def __init__(self):
        super().__init__()
        self.side_buttons = []
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setFixedWidth(320)
        sidebar.setStyleSheet("background-color: rgba(11, 18, 21, 0.4); border: none;")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 30, 0, 20)
        side_layout.setSpacing(15)

        # 按钮名称列表
        btn_names = ["User guide"]

        for name in btn_names:
            btn = QPushButton(name)
            btn.setObjectName("sideBtnCyan")  # 默认青色
            btn.setFixedSize(270, 60)
            btn.setCursor(Qt.PointingHandCursor)

            # 处理文字过长省略
            self.apply_elided_text(btn, name, available_width=200)

            # [关键修改] 将完整名称存储在 property 中，确保逻辑判断准确
            btn.setProperty("fullName", name)

            btn.clicked.connect(self.on_btn_clicked)
            self.side_buttons.append(btn)
            side_layout.addWidget(btn, 0, Qt.AlignHCenter)

        side_layout.addStretch()
        main_layout.addWidget(sidebar)

    def apply_elided_text(self, button, text, available_width):
        font = button.font()
        font.setPixelSize(14)
        font.setWeight(600)
        metrics = QFontMetrics(font)
        elided_text = metrics.elidedText(text, Qt.ElideRight, available_width)
        button.setText(elided_text)
        if elided_text != text: button.setToolTip(text)

    def reset_buttons(self):
        """
        供外部或内部调用：重置所有按钮为未激活状态（青色）。
        """
        for btn in self.side_buttons:
            btn.setObjectName("sideBtnCyan")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def on_btn_clicked(self):
        """
        [交互逻辑说明]
        1. 维护按钮的互斥高亮状态。
        2. 触发帮助文档相关的功能接口。
        """
        sender = self.sender()
        if not sender: return

        # 检查点击前状态
        was_active = (sender.objectName() == "sideBtnGold")

        # 重置所有按钮
        self.reset_buttons()

        # 如果点击前是未激活状态，则激活它并执行逻辑
        if not was_active:
            sender.setObjectName("sideBtnGold")
            sender.style().unpolish(sender)
            sender.style().polish(sender)

            # [接口调用] 获取完整功能名称并分发任务
            full_name = sender.property("fullName")
            self.dispatch_task(full_name)

    # =========================================================================
    # [API SECTION] 开发者接口区域
    # =========================================================================

    def dispatch_task(self, btn_name):
        """
        [任务分发器] 根据按钮名称路由到具体的算法函数
        """
        print(f"[接口调试] 用户点击了帮助模块: {btn_name}")

        if btn_name == "User guide":
            self.api_open_user_guide()

        else:
            print(f"[警告] 未知的按钮功能: {btn_name}")

    # -------------------------------------------------------------------------
    # 下方为具体功能的预留接口，请开发者在 TODO 处填入实现逻辑
    # -------------------------------------------------------------------------

    def api_open_user_guide(self):
        guide_path = str(USER_GUIDE_PATH).strip()
        if not guide_path:
            QMessageBox.warning(self, "User Guide", "Please set USER_GUIDE_PATH in page_help.py.")
            return

        guide_path = os.path.normpath(guide_path)
        if not os.path.exists(guide_path):
            QMessageBox.warning(self, "User Guide", f"User guide file not found:\n{guide_path}")
            return

        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(guide_path))
        if not opened:
            QMessageBox.warning(self, "User Guide", f"Failed to open user guide:\n{guide_path}")
        return

        """
        [接口说明] User guide
        功能：打开用户手册（通常是 PDF 文件或在线网页）。
        """
        # TODO: ===============================================================
        # [开发者注意]: 请在此处编写打开帮助文档的逻辑
        #
        # 示例 1 (打开本地 PDF):
        #   import os
        #   os.startfile("docs/UserGuide.pdf")
        #
        # 示例 2 (打开在线网页):
        #   from PyQt5.QtGui import QDesktopServices
        #   from PyQt5.QtCore import QUrl
        #   QDesktopServices.openUrl(QUrl("https://www.your-website.com/help"))
        # =====================================================================
        print("TODO: 执行 Open User Guide 逻辑...")

        # 演示代码：打开一个示例链接 (实际交付时可注释掉)
        # QDesktopServices.openUrl(QUrl("https://www.google.com"))
