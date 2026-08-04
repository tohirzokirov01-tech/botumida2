"""
Root Entry Point for Telegram Online Course Bot & FastAPI Admin Panel
Run directly: python main.py
"""
import sys
import os

# Add root folder to python module search path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Starting Telegram Bot & FastAPI Admin on port {port}")
    print(f"📊 Admin Panel available at: http://localhost:{port}/admin")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
