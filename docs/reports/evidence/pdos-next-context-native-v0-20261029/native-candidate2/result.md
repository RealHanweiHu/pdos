# 上下文候选原生控制回放

使用脚本端驱动实际本地状态与注册图；任务分、答案/引用语义及真实计量未评分。

| 题目 | F | 原生绑定 | 控制状态 | 脚本派发 |
| --- | ---: | --- | --- | ---: |
| CTX-01 | 48000 | bound | native_control_checks_passed | 32 |
| CTX-01 | 64000 | bound | native_control_checks_passed | 32 |
| CTX-02 | 48000 | bound | native_control_checks_passed | 18 |
| CTX-02 | 64000 | bound | native_control_checks_passed | 18 |
| CTX-03 | 48000 | bound | native_control_checks_passed | 14 |
| CTX-03 | 64000 | bound | native_control_checks_passed | 14 |
| CTX-04 | 48000 | partial | native_control_checks_passed | 2 |
| CTX-04 | 64000 | partial | native_control_checks_passed | 2 |
| CTX-05 | 48000 | bound | native_control_checks_passed | 3 |
| CTX-05 | 64000 | bound | native_control_checks_passed | 3 |
| CTX-06 | 48000 | bound | native_control_checks_passed | 6 |
| CTX-06 | 64000 | bound | native_control_checks_passed | 6 |
| CTX-07 | 48000 | bound | native_control_checks_passed | 6 |
| CTX-07 | 64000 | bound | native_control_checks_passed | 6 |
| CTX-08 | 48000 | bound | native_control_checks_passed | 12 |
| CTX-08 | 64000 | bound | native_control_checks_passed | 12 |
| CTX-09 | 48000 | partial | native_mechanics_passed_scenario_item_alignment_unbound | 4 |
| CTX-09 | 64000 | partial | native_mechanics_passed_scenario_item_alignment_unbound | 4 |
| CTX-10 | 48000 | bound | native_control_checks_passed | 0 |
| CTX-10 | 64000 | bound | native_control_checks_passed | 0 |
| CTX-11 | 48000 | not_executable | context_admission_blocked | 5 |
| CTX-11 | 64000 | bound | native_mechanics_passed_model_quality_not_scored | 17 |
| CTX-12 | 48000 | partial | CONTEXT_INCOMPLETE | 54 |
| CTX-12 | 64000 | bound | native_control_checks_passed | 55 |

pytest退出码：0。绑定状态按实际输出保留，partial/not_executable不计为完整场景通过。
没有真实模型/embedding调用，也不以脚本输出评价模型正确率。
