package com.ai.codex.shizukuprobe;

interface IQualificationService {
    String collectContext() = 1;
    String runFixed() = 2;
    void destroy() = 16777114;
}
