"""UI 层：PySide6 页面、窗口与信号。

所有 SQLite/Provider/Parser 与长操作都在 worker 线程执行，主线程只通过
信号接收 DTO/不可变数据；每个 worker 线程内创建的 Service 连接只在创建
它的线程内开闭，不跨线程共享。
"""
