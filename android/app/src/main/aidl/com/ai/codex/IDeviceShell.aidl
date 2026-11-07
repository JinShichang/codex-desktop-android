package com.ai.codex;
interface IDeviceShell {
    String execute(String request) = 1;
    int uid() = 2;
    void destroy() = 16777114;
}
