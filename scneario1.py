#!/usr/bin/env python3
"""
VULNERABLE ENTERPRISE MCP SERVER (Streamable HTTP)
FOR AUTHORIZED SECURITY TESTING ONLY.

Exposes tools:
- query_financial_data  (SQL injection)
- generate_report       (path traversal / arbitrary file read)
- export_data           (command injection via shell=True)
- get_client_secrets    (IDOR: no auth on client_id)

Transport: Streamable HTTP using FastMCP.
"""

import logging
import sqlite3
import subprocess
import json
import os                      # ⬅️ NEW for Render PORT
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Context  # not strictly needed but useful later

# --------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("vuln-mcp-server")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "financial_data.db"


# --------------------------------------------------------------------
# Database initialization
# --------------------------------------------------------------------
def init_database() -> None:
    """Initialize enterprise-like SQLite DB with juicy data."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Clients table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            client_id TEXT PRIMARY KEY,
            company_name TEXT,
            revenue REAL,
            contact_email TEXT,
            api_key TEXT,
            internal_notes TEXT
        )
        """
    )

    # Transactions table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT,
            amount REAL,
            description TEXT,
            date TEXT,
            confidential_notes TEXT
        )
        """
    )

    # System config
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            description TEXT
        )
        """
    )

    # Sample data (fake but realistic)
    cur.executemany(
        """
        INSERT OR REPLACE INTO clients
        (client_id, company_name, revenue, contact_email, api_key, internal_notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "CLIENT_001",
                "Stark Industries",
                2_500_000.0,
                "tony@stark.com",
                "sk_live_51Mn8s9JzQpQn8nKj9H8s9Jz",
                "VIP Client - Handle with care",
            ),
            (
                "CLIENT_002",
                "Wayne Enterprises",
                1_800_000.0,
                "bruce@wayne.com",
                "sk_live_72Kp9RzXwVtB4mNp7RzXwVtB",
                "High security requirements",
            ),
            (
                "CLIENT_003",
                "Oscorp Industries",
                1_200_000.0,
                "norman@oscorp.com",
                "sk_live_93Lq0SaYxUuC5oOq8SaYxUuC",
                "Payment delays - monitor closely",
            ),
        ],
    )

    cur.executemany(
        """
        INSERT OR REPLACE INTO system_config
        (key, value, description)
        VALUES (?, ?, ?)
        """,
        [
            ("database_url", "postgresql://admin:QuantumDB2024!@prod-db:5432", "Production database"),
            ("aws_access_key", "AKIAIOSFODNN7EXAMPLE", "AWS access key"),
            ("aws_secret_key", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "AWS secret key"),
            ("backup_server", "192.168.1.100", "Internal backup server"),
            ("admin_password", "Admin@Secure123!", "Admin dashboard password"),
        ],
    )

    conn.commit()
    conn.close()
    logger.info("✅ Enterprise database initialized at %s", DB_PATH)


def create_test_files() -> None:
    """Create some local files to demonstrate path traversal / secret leakage."""
    (BASE_DIR / "report_template.html").write_text(
        "<html><body><h1>Financial Report</h1><p>Confidential summary...</p></body></html>",
        encoding="utf-8",
    )

    (BASE_DIR / "secrets.txt").write_text(
        "DATABASE_PASSWORD=QuantumSecure2024!\n"
        "JWT_SECRET=very-secret-jwt-key-12345\n"
        "ENCRYPTION_KEY=super-secret-encryption-key-xyz\n"
        "API_MASTER_KEY=master-api-key-do-not-share\n",
        encoding="utf-8",
    )

    logger.info("✅ Local test files created (report_template.html, secrets.txt)")


# --------------------------------------------------------------------
# FastMCP server over Streamable HTTP
# --------------------------------------------------------------------
# Render sets PORT in environment → use it instead of hardcoding 8000
PORT = int(os.getenv("PORT", "8000"))

mcp = FastMCP(
    name="quantum-financial-mcp",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,  # fine for your FYP scenarios
)


# --------------------------------------------------------------------
# Tools (vulnerable on purpose)
# --------------------------------------------------------------------
@mcp.tool()
def query_financial_data(sql_query: str) -> str:
    """
    VULN: SQL Injection
    Executes raw SQL against financial_data.db with NO sanitization.
    """
    logger.warning("⚠️ Executing raw SQL: %s", sql_query)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        # 🚨 Direct execution: SQLi playground
        cur.execute(sql_query)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []

        result = {
            "status": "success",
            "query": sql_query,
            "columns": cols,
            "results": rows,
            "count": len(rows),
        }
    except Exception as e:
        result = {"status": "error", "error": str(e), "query": sql_query}
    finally:
        conn.close()

    # Return as JSON string in text content (easy to parse on attacker side)
    return json.dumps(result, indent=2)


@mcp.tool()
def generate_report(template_path: str, output_format: str = "pdf") -> str:
    """
    VULN: Path Traversal / Arbitrary File Read
    Reads ANY file path given by client (no validation).
    """
    logger.warning("⚠️ generate_report reading path: %s", template_path)
    try:
        path = Path(template_path)
        # allow relative and absolute (even ../../../etc/passwd)
        content = path.read_text(encoding="utf-8", errors="ignore")
        result = {
            "status": "report_generated",
            "template_path": str(path),
            "format": output_format,
            "content_preview": content[:500],
            "note": "Report processing completed (NO security checks)",
        }
    except Exception as e:
        result = {"status": "error", "error": str(e), "template_path": template_path}

    return json.dumps(result, indent=2)


@mcp.tool()
def export_data(export_command: str, format: str = "csv") -> str:
    """
    VULN: Command Injection
    Runs the given export_command with shell=True.
    """
    full_cmd = f"echo 'Exporting data...' && {export_command}"
    logger.warning("⚠️ Running shell command: %s", full_cmd)

    try:
        proc = subprocess.run(
            full_cmd,
            shell=True,  # 🚨 command injection
            capture_output=True,
            text=True,
            timeout=30,
        )
        result = {
            "status": "export_completed",
            "command": full_cmd,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "return_code": proc.returncode,
            "format": format,
        }
    except subprocess.TimeoutExpired:
        result = {"status": "error", "error": "command timeout", "command": full_cmd}
    except Exception as e:
        result = {"status": "error", "error": str(e), "command": full_cmd}

    return json.dumps(result, indent=2)


@mcp.tool()
def get_client_secrets(client_id: str) -> str:
    """
    VULN: IDOR (Insecure Direct Object Reference)
    Anyone who knows a client_id can read API keys and internal notes.
    No auth / access control at all.
    """
    logger.warning("⚠️ IDOR: fetching secrets for client_id=%s with NO auth", client_id)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT client_id, company_name, api_key, internal_notes "
            "FROM clients WHERE client_id = ?",
            (client_id,),
        )
        row = cur.fetchone()
        if row:
            result = {
                "status": "success",
                "client_id": row[0],
                "company_name": row[1],
                "api_key": row[2],
                "internal_notes": row[3],
            }
        else:
            result = {"status": "error", "error": "Client not found", "client_id": client_id}
    except Exception as e:
        result = {"status": "error", "error": str(e), "client_id": client_id}
    finally:
        conn.close()

    return json.dumps(result, indent=2)


# --------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------
def main() -> None:
    init_database()
    create_test_files()

    logger.info("🚀 Starting vulnerable MCP server over Streamable HTTP")
    logger.info(f"📡 Listening on http://0.0.0.0:{PORT}/mcp")   # ⬅️ show real port
    logger.info("⚠️ FOR AUTHORIZED TESTING ONLY")

    # This uses the official streamable HTTP transport.
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
