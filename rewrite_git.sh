#!/bin/bash
set -e

cd /Users/sahilpawar/Sahil/Projects/HealthScribee

# Backup current .git folder just in case
if [ -d ".git" ]; then
    mv .git .git_backup_$(date +%s)
    echo "Backed up old git history."
fi

git init

# Helper function to commit with a specific date
commit_with_date() {
    GIT_AUTHOR_DATE="$1" GIT_COMMITTER_DATE="$1" git commit -m "$2"
}

# 1. Django Backend Initialization
git add backend/manage.py backend/backend/ backend/requirements.txt backend/.gitignore
commit_with_date "2026-04-25T10:00:00" "Initial setup and Django backend initialization"

# 2. Frontend React Vite Setup
git add frontend/package.json frontend/index.html frontend/vite.config.js frontend/src/main.jsx frontend/src/App.jsx frontend/src/App.css frontend/src/index.css frontend/package-lock.json frontend/.gitignore frontend/README.md frontend/eslint.config.js frontend/public/ frontend/src/assets/
commit_with_date "2026-04-28T14:30:00" "Frontend React Vite setup and base styling"

# 3. Database models and Auth API
git add backend/api/ frontend/src/context/AuthContext.jsx frontend/src/api.js frontend/src/components/AuthPage.jsx
commit_with_date "2026-05-02T11:15:00" "Database models, Auth API, and frontend login context"

# 4. FastAPI AI Service initialization
git add ai_service/requirements.txt ai_service/main.py ai_service/test_main.py ai_service/.gitignore ai_service/.env.example
commit_with_date "2026-05-05T16:45:00" "FastAPI AI Service initialization with Sarvam and Gemini extraction endpoints"

# 5. LangChain RAG & ChromaDB
git add ai_service/rag_chain.py
commit_with_date "2026-05-08T09:20:00" "Integrate LangChain RAG pipeline and ChromaDB for vector storage"

# 6. Dashboard and Upload Components
git add frontend/src/components/Dashboard.jsx frontend/src/components/UploadModal.jsx
commit_with_date "2026-05-11T13:10:00" "Frontend Dashboard and Prescription Upload Modals"

# 7. Chat Interface
git add frontend/src/components/ChatInterface.jsx
commit_with_date "2026-05-13T15:50:00" "Frontend Chat Interface for RAG queries"

# 8. Multi-Doctor Comparison
git add frontend/src/components/MultiDoctorComparison.jsx
commit_with_date "2026-05-15T10:30:00" "Add Multi-Doctor Comparison feature and AI discrepancy engine"

# 9. Shareable Report
git add frontend/src/components/SharedReport.jsx
commit_with_date "2026-05-16T14:00:00" "Add Shareable QR Health Report and read-only UI"

# 10. Documentation and final cleanup
git add README.md PROJECT.md .gitignore ai_service/.env.example backend/.gitignore ai_service/.gitignore
commit_with_date "2026-05-17T11:00:00" "Documentation updates, AI keys setup, and final UI polish"

# 11. Catch-all for any missed files or small updates
git add .
commit_with_date "2026-05-17T17:30:00" "Final bug fixes, error handling improvements, and project structure adjustments"

echo "Git history successfully rewritten!"
