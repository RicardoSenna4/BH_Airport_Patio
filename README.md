# AeroOps BH — MVP de Gestão Operacional Aeroportuária

MVP para digitalizar inspeções de pátio, registrar não conformidades, validar ocorrências e acompanhar indicadores operacionais.

## Escopo desta versão

- perfis: Fiscal, Supervisor, Analista e Coordenação;
- autenticação JWT e autorização por perfil;
- inspeção de pátio com checklist, observação, quadrícula e evidências;
- abertura automática de ocorrência para item não conforme;
- fluxo `ABERTA → EM_VALIDACAO → VALIDADA/REJEITADA → EM_TRATAMENTO → RESOLVIDA`;
- painel com totais, recorrências, distribuição por status e produtividade;
- alertas de vencimento de inspeções de equipamentos;
- trilha de auditoria das alterações.
- mapa operacional com quadrículas, gravidade e consulta de ocorrências;
- gestão de equipamentos com cadastro e controle de validade;
- gestão de usuários protegida por perfil;
- relatórios de produtividade, áreas e inspeções por dia;
- interface adaptada aos tokens semânticos do Confins Design System.

## Tecnologias

- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Pydantic e JWT.
- Banco: SQLite no desenvolvimento; PostgreSQL em produção.
- Frontend: React 18, TypeScript e Vite.
- Visual: tokens e folha compilada do Confins Design System, com paleta BH Airport, foco visível e responsividade.

## Execução local

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API: `http://localhost:8000`  
Swagger: `http://localhost:8000/docs`

Usuários demonstrativos criados no primeiro início (senha `Aero@123`):

- `fiscal@aeroops.local`
- `supervisor@aeroops.local`
- `analista@aeroops.local`
- `coordenacao@aeroops.local`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Interface: `http://localhost:5173`

## Produção

Defina `DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/aeroops`, altere `SECRET_KEY` e restrinja `CORS_ORIGINS`.

Consulte [docs/ESPECIFICACAO.md](docs/ESPECIFICACAO.md) para requisitos, telas, regras e modelo de dados.
