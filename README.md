# AeroOps BH

Sistema de gestão operacional aeroportuária para inspeções, não conformidades, ocorrências, equipamentos, checklists e indicadores do BH Airport.

## Funcionalidades

- inspeções com rascunho, checklist, quadrícula e evidências;
- geração e tratamento de ocorrências por fluxo operacional;
- perfis Fiscal, Supervisor, Analista, Coordenação e Administrador;
- equipamentos, mapa operacional, relatórios e trilha de auditoria;
- autenticação com Argon2id, MFA TOTP, sessões revogáveis, CSRF e rate limit;
- API FastAPI, frontend React e persistência PostgreSQL/Supabase.

## Estrutura

```text
backend/
  alembic/       migrações versionadas
  app/           API, domínio, segurança e persistência
  scripts/       migração legada, backup e restore
  tests/         testes automatizados
frontend/
  src/           aplicação React e estilos Confins
docs/
  ESPECIFICACAO.md
  TESTES.md
  OPERACAO.md
SECURITY.md       política e controles de segurança
```

## Requisitos

- Python 3.12 ou superior;
- Node.js 22 ou superior;
- PostgreSQL para homologação/produção;
- `pg_dump` e `pg_restore` para os procedimentos de backup.

## Desenvolvimento local

### Backend

```bash
cd backend
python -m venv .venv
```

Ative o ambiente (`.venv\Scripts\activate` no Windows ou `source .venv/bin/activate` em Linux/macOS) e execute:

```bash
pip install -r requirements-dev.txt
cp .env.example .env  # no Windows, use: Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

API: `http://localhost:8000`  
Swagger em desenvolvimento: `http://localhost:8000/docs`

Com `SEED_DEMO_USERS=true`, o ambiente local cria contas `fiscal`, `supervisor`, `analista`, `coordenacao` e `administrador` no domínio `@aeroops.local`, usando a senha demonstrativa `Aero@123`. Essa configuração é bloqueada em produção.

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

Interface: `http://localhost:5173`

## Qualidade

```bash
cd backend
pytest -q
python -m pip_audit -r requirements.txt
python -m bandit -q -r app scripts alembic -lll

cd ../frontend
npm run build
npm audit --omit=dev
```

O CI executa testes e build em cada `push` e `pull_request`. O roteiro completo está em [docs/TESTES.md](docs/TESTES.md).

## Produção

O `.env.example` documenta as variáveis disponíveis, mas seus valores locais não são adequados para produção. Antes da publicação, siga integralmente [docs/OPERACAO.md](docs/OPERACAO.md) e [SECURITY.md](SECURITY.md). Não publique enquanto a credencial do banco anteriormente compartilhada não tiver sido rotacionada e os controles externos do Supabase não estiverem ativos.

## Documentação

- [Especificação funcional e técnica](docs/ESPECIFICACAO.md)
- [Testes e aceite](docs/TESTES.md)
- [Operação e implantação](docs/OPERACAO.md)
- [Política de segurança](SECURITY.md)
