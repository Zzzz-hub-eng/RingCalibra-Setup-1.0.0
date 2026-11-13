# -*- coding: utf-8 -*-
"""RingCalibra 交互式标定编辑器启动入口:  python run_app.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk

from ringcalibra.editor_app import RingEditorApp


def main():
    root = tk.Tk()
    RingEditorApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
