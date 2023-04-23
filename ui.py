import sys
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QFrame, QDesktopWidget
from PyQt5.QtCore import Qt


class Example(QWidget):
    
    def __init__(self):
        super().__init__()
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle('FrameFusion')
        self.setWindowState(Qt.WindowMaximized)  # maximize the window by default
        
        # Add a frame for the sidebar menu
        sidebar = QFrame(self)
        sidebar.setFrameShape(QFrame.StyledPanel)
        sidebar.setFixedWidth(100)
        
        # Set the height of the sidebar menu to the height of the screen
        desktop = QDesktopWidget()
        sidebar.setFixedHeight(desktop.screenGeometry().height())
        
        sidebarLayout = QVBoxLayout(sidebar)
        
        # Add buttons to the sidebar menu
        button1 = QPushButton('Button 1', self)
        sidebarLayout.addWidget(button1)
        button2 = QPushButton('Button 2', self)
        sidebarLayout.addWidget(button2)
        button3 = QPushButton('Button 3', self)
        sidebarLayout.addWidget(button3)
        
        # Add a label
        label = QLabel('Hello, world!', self)
        label.move(120, 20)
        
        # Add a button
        button = QPushButton('Click me', self)
        button.setToolTip('This is a tooltip')
        button.move(120, 60)
        
        self.show()
        
        
if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = Example()
    sys.exit(app.exec_())
