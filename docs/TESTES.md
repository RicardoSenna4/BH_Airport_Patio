# Testes e aceite

## Testes automatizados

Na raiz do projeto:

```bash
cd backend
pytest -q
cd ../frontend
npm ci
npm run build
```

A integração contínua em `.github/workflows/ci.yml` repete esses comandos em cada `push` e `pull_request`.

| Arquivo | Cobertura principal |
|---|---|
| `test_health.py` | disponibilidade e versão da API |
| `test_flow_smoke.py` | inspeção, não conformidade e ocorrência |
| `test_admin_features.py` | usuários, equipamentos, mapa e relatórios |
| `test_checklists.py` | criação, revisão e publicação de modelos |
| `test_security.py` | refresh, revogação, rate limit, RBAC, CORS e cabeçalhos |
| `test_auth_hardening.py` | cookies, CSRF, MFA, sessões e alteração de senha |
| `test_upload_security.py` | imagem real, autorização, nome seguro e download privado |
| `test_acceptance.py` | permissões e fluxos por perfil |

Antes de liberar uma versão, execute também:

```bash
python -m pip_audit -r requirements.txt
python -m bandit -q -r app scripts alembic -lll
npm audit --omit=dev
```

## Matriz de permissões validada

Legenda: L = leitura; C = criar; E = editar/transicionar; P = publicar; A = administrar.

| Recurso | Fiscal | Supervisor | Analista | Coordenação | Administrador |
|---|---:|---:|---:|---:|---:|
| Inspeções próprias | L/C/E | L/C/E | L/C/E | L/C/E | L/C/E |
| Ocorrências | L | L/E validação | L/E tratamento | L | L |
| Equipamentos | L | L | L/C/E | L/C/E | L/C/E |
| Usuários | — | — | — | L | L/C/E/A |
| Checklist: criar/submeter | C/E | C/E | C/E | C/E | C/E |
| Checklist: editar/publicar | — | — | — | E/P | E/P/A |
| Relatórios, mapa e anexos autorizados | L | L | L | L | L |
| Auditoria | — | — | — | L | L |

## Roteiro de aceite manual

Execute em homologação com dados fictícios e representantes dos cinco perfis.

| ID | Cenário | Resultado esperado |
|---|---|---|
| UAT-01 | Login, MFA, erro e bloqueio | acesso válido; erro genérico; bloqueio auditado |
| UAT-02 | Salvar e retomar rascunho | dados preservados e envio posterior permitido |
| UAT-03 | Não conformidade incompleta | descrição, gravidade, evidência e local exigidas |
| UAT-04 | Enviar inspeção completa | inspeção imutável e ocorrência automática |
| UAT-05 | Fluxo de ocorrência | Supervisor decide; Analista trata e resolve |
| UAT-06 | Acesso por perfil/objeto | ações indevidas retornam 403/404 sem vazar dados |
| UAT-07 | Upload inválido e autorizado | falso arquivo rejeitado; download privado |
| UAT-08 | Checklist administrativo | submissão, revisão e publicação respeitam a matriz |
| UAT-09 | Indicadores e mapa | totais refletem os registros criados |
| UAT-10 | Sessão e troca de senha | refresh funciona; logout/troca revogam sessões |
| UAT-11 | Desktop, celular e teclado | fluxos críticos legíveis, responsivos e navegáveis |
| UAT-12 | Restauração isolada | integridade conferida e RPO/RTO registrados |

## Critério de saída

Todos os cenários críticos aprovados, nenhum defeito alto aberto, matriz confirmada, backup restaurado em ambiente isolado e aceite registrado com versão/commit, ambiente, participantes, evidências, ressalvas e responsável.
