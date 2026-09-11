# Go Control Plane

**Status: NOT IMPLEMENTED。** 当前 Phase 1 准备阶段不写 Go 业务代码；Phase 2 才开始本服务 MVP。

长期管理 HTTP API、身份、Project / Repository、Task 生命周期与状态机、消息队列、热状态、SSE、Tool Gateway、Sandbox、审批、并发、幂等、限流及平台 Observability。Go 管 Task / Service Orchestration，Python 管 LLM Orchestration；这里不建立第二套主要 Agent Runtime。

按需要逐步形成 Handler/API、Application、Domain、Infrastructure 边界。Phase 5 接管安全工具执行；具体时间见 [roadmap](../../docs/roadmap.md)。今天没有 go.mod、空 package、API、数据库适配或服务启动入口。
