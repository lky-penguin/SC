# SC

基于贝叶斯网络的复杂系统态势感知软件。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Element Plus
- 后端：FastAPI、SQLAlchemy、PostgreSQL
- 算法服务：Java / Weka 朴素贝叶斯算法服务

## 目录结构

```text
backend/        FastAPI 后端、JAR 依赖与运行配置
frontend/       Vue 3 前端
java/           Java 算法源码（仅用于编辑与重新构建 JAR）
scripts/        Java 服务构建脚本
start.ps1       Windows 本地启动脚本
stop.ps1        Windows 本地停止脚本
```

## 本地运行

前置依赖：Python 3.12、Node.js、Docker Desktop、JDK。

```powershell
python -m pip install -r backend/requirements.txt
Push-Location frontend
npm install
Pop-Location

Copy-Item .env.example backend/app/.env
.\start.ps1
```

停止服务：

```powershell
.\stop.ps1
```

## 说明

- 数据集、运行日志、PID、上传数据、训练产物、模型文件、依赖目录以及部署配置和压缩包不会提交到 Git。
- `backend/lib/*.jar` 按项目约定不纳入版本控制，后端运行时直接使用这些 JAR。首次运行前请按 `scripts/build_*.ps1` 与 `java/algorithm-src/README.md` 的说明准备或构建所需 JAR。`java/` 只保存算法源码，不参与后端运行。
