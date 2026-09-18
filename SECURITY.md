# Política de segurança

## Versão suportada

A versão mantida é a `0.4.x`. Correções de segurança são aplicadas na branch principal e devem passar pela integração contínua antes da publicação.

## Como relatar uma vulnerabilidade

Não publique credenciais, dados pessoais ou detalhes exploráveis em uma issue pública. Use o recurso privado de *Security Advisory* do repositório, quando habilitado, ou comunique diretamente o responsável pelo projeto. Inclua versão/commit, impacto, passos mínimos para reprodução e evidências sem dados reais.

## Controles implementados

- Argon2id para senhas, com migração automática de hashes legados no login;
- access/refresh tokens vinculados a sessões revogáveis em cookies `HttpOnly` e `SameSite=Strict`;
- CSRF, MFA TOTP, limitação de tentativas persistida e bloqueio temporário;
- autorização por perfil e por objeto, auditoria e logs JSON com `X-Request-ID`;
- validação, decodificação e recodificação de imagens, limite de tamanho e integração ClamAV;
- cabeçalhos CSP, HSTS em produção, CORS e hosts permitidos restritos;
- RLS habilitado e privilégios públicos revogados nas tabelas PostgreSQL/Supabase;
- migrações Alembic e verificação automatizada de dependências no CI.

## Requisitos para produção

O modo `production` falha na inicialização se os principais controles não estiverem configurados. Segredos devem permanecer no cofre da plataforma, nunca no Git. Contas demonstrativas, criação automática de schema e documentação interativa devem ficar desativadas. A senha do banco previamente compartilhada deve ser rotacionada antes de qualquer publicação.

Os procedimentos de implantação, backup e resposta a incidentes estão em [docs/OPERACAO.md](docs/OPERACAO.md). A estratégia de verificação está em [docs/TESTES.md](docs/TESTES.md).
