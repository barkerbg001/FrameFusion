# FrameFusion

**FrameFusion** is a Python-based video generator that creates videos using image folders and audio clips. It includes a FastAPI backend and a React frontend to streamline usage across various video styles.

## 📁 Project Structure

```
FrameFusion/
├── api/               # FastAPI backend (entrypoint: main.py, requirements.txt inside)
├── frontend/          # React frontend for interaction
└── README.md
```

## 🎬 Features

- Generate videos from images and audio
- Available API endpoints:
  - `/lofi` – Lofi-style loop
  - `/shorts` – Vertical short-form
  - `/video` – Standard format
  - `/youtube` – YouTube-ready format
- React UI for managing and triggering jobs

## 🔧 Setup

### 1. Backend (FastAPI)

Install dependencies (from inside the `api` folder):

```bash
cd api
pip install -r requirements.txt
```

Run the API:

```bash
uvicorn main:app --reload
```

### 2. Frontend (React)

Inside the `frontend` folder:

```bash
cd ../frontend
npm install
npm run dev
```

## 📂 Folder Usage

- `images/` — Subfolders represent video sources
- `audio/` — Audio files randomly selected
- `output/` — Output videos are saved here

## 🔁 Endpoints

| Method | Endpoint   | Description                  |
|--------|------------|------------------------------|
| GET    | `/lofi`    | Generate lofi loop video     |
| GET    | `/shorts`  | Generate vertical short      |
| GET    | `/video`   | Generate standard video      |
| GET    | `/youtube` | Generate YouTube-style video |

Each endpoint uses similar logic with format-specific adjustments.

## 📄 License

MIT License — free to use and modify.
