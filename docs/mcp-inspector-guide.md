# How to Connect MCP Inspector to CampusMate MCP Server

This guide demonstrates how to test and verify the CampusMate MCP server standalone using the official **MCP Inspector**.

---

## 1. Start the CampusMate MCP Server

In a terminal, ensure the database is seeded and launch the server:

```powershell
# 1. Reset and populate seed data (if not already done)
& "d:\NewProject\campusmate\.venv\Scripts\python.exe" -m campusmate.data.seed_data --reset

# 2. Start the MCP server on port 8000
& "d:\NewProject\campusmate\.venv\Scripts\python.exe" -m campusmate.server.app.main --port 8000
```

You should see:
```text
============================================================
 CampusMate MCP Server (Spec 2025-11-25 / SDK 2.3.0)
 Streamable HTTP endpoint: http://127.0.0.1:8000/mcp
 Health check:             http://127.0.0.1:8000/health
============================================================
```

You can verify the server is running by opening `http://127.0.0.1:8000/health` in your browser.

---

## 2. Launch the MCP Inspector

Open a second terminal and run:

```bash
npx -y @modelcontextprotocol/inspector
```

This starts the Inspector web interface (typically at `http://localhost:5173` or similar).

---

## 3. Connect via Streamable HTTP

In the MCP Inspector interface:
1. **Transport Type**: Select **Streamable HTTP** (or HTTP / SSE depending on Inspector version).
2. **Server URL**: Enter `http://127.0.0.1:8000/mcp`
3. **Custom Headers**: Add the Bearer authorization header:
   ```text
   Authorization: Bearer token-alice-demo-cs
   ```
4. Click **Connect**.

---

## 4. Test the Tools

1. Once connected, switch to the **Tools** tab.
2. Click **List Tools**. You will see:
   - **`get_timetable`** with full description and JSON schema.
3. Test **Alice's Timetable**:
   - Argument: `{"date": "2026-10-12"}`
   - Click **Run Tool**.
   - Output shows Alice's 4 classes on Monday (Database Systems, OS, Software Eng, Algorithms Lab) and the spoken summary.
4. Test **Student Isolation**:
   - Reconnect with Bob's token:
     `Authorization: Bearer token-bob-demo-ee`
   - Run `get_timetable` with date `"2026-10-16"` (Friday).
   - Result: 0 classes ("You have no classes scheduled for Friday, October 16"), proving identity is isolated to the authenticated session without passing any `student_id`.
