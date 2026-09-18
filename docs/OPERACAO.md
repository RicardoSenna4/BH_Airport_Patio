# Operação e implantação

## Implantação segura

- rotacionar a senha PostgreSQL anteriormente compartilhada e atualizar o cofre;
- configurar `ENVIRONMENT=production`, `SEED_DEMO_USERS=false`, `AUTO_CREATE_SCHEMA=false` e `DOCS_ENABLED=false`;
- configurar `COOKIE_SECURE=true`, `REQUIRE_PRIVILEGED_MFA=true`, `REQUIRE_MALWARE_SCAN=true` e `CLAMAV_HOST`;
- gerar uma nova `SECRET_KEY` com pelo menos 32 bytes;
- usar PostgreSQL com `sslmode=verify-full` e `sslrootcert` da CA validada;
- limitar CORS e hosts ao domínio HTTPS oficial;
- desativar contas demonstrativas e cadastrar contas nominativas com MFA;
- usar armazenamento privado, durável e versionado para evidências;
- enviar logs JSON a um coletor com alertas e retenção definida;
- no Supabase, habilitar MFA administrativo, SSL Enforcement, restrição de rede e revisar backup/PITR.

## Migrações

Instalação nova:

```bash
cd backend
alembic upgrade head
```

Banco legado já existente, somente após confirmar que o schema está criado:

```bash
alembic stamp head
python scripts/migrate_security.py
```

`stamp` não cria tabelas. Nunca o use para simular uma migração que não foi aplicada.

## Backup e restauração

Política inicial: backup diário, retenção mínima de 30 dias, RPO de 24 horas e RTO de 4 horas, sujeitos à aprovação operacional. Evidências armazenadas fora do banco precisam de backup próprio.

```bash
cd backend
python scripts/backup_postgres.py
```

Para validar um dump, use exclusivamente um banco descartável cujo nome contenha `restore`, `test` ou `staging`:

```bash
RESTORE_DATABASE_URL=postgresql+psycopg://... \
BACKUP_FILE=backups/aeroops-AAAAMMDD.dump \
ALLOW_ISOLATED_RESTORE=yes-isolated-only \
python scripts/verify_restore.py
```

Nunca teste restauração sobre produção. Registre backup utilizado, horários, contagens, divergências e responsável.

## Resposta a incidentes

1. Conter: revogar sessões, desativar contas, bloquear a origem e isolar o componente.
2. Rotacionar: banco, `SECRET_KEY`, chaves de implantação e credenciais afetadas.
3. Investigar: correlacionar `auth_events`, `audit_logs`, `X-Request-ID`, logs da API e do provedor.
4. Recuperar: corrigir a causa, validar o artefato e restaurar somente em destino isolado.
5. Comunicar: envolver operação, segurança, encarregado e jurídico; avaliar comunicação à ANPD e titulares.
6. Encerrar: documentar impacto, linha do tempo, evidências, decisões e prevenção.

Mensalmente, revise contas privilegiadas/MFA, eventos de autenticação, vulnerabilidades e o resultado do exercício de restauração.
