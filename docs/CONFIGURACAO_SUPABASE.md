# Configuração externa — Supabase e Render

Este projeto usa o Supabase somente para duas responsabilidades:

1. autenticar usuário e senha pelo Supabase Auth;
2. guardar a BASE DADOS persistente já cifrada pela aplicação com AES-256-GCM.

A senha nunca é gravada no projeto. A chave secreta do Supabase e a chave que cifra a BASE DADOS existem somente nas variáveis protegidas do Render.

## 1. Criar o projeto no Supabase

1. Acesse o painel do Supabase e crie um projeto.
2. Aguarde a inicialização do banco.
3. Em **Project Settings > API**, copie:
   - a URL do projeto;
   - a chave `Publishable` (`sb_publishable_...`);
   - a chave `Secret` (`sb_secret_...`).
4. Nunca coloque a chave `Secret` no navegador, em JavaScript, no GitHub ou em arquivo versionado.

## 2. Criar a tabela persistente

Abra **SQL Editor**, crie uma consulta e execute exatamente:

```sql
create table if not exists public.contas_a_pagar_bases (
  user_id uuid primary key references auth.users(id) on delete cascade,
  ciphertext text not null,
  nonce text not null,
  revision text not null,
  row_count integer not null check (row_count > 0),
  updated_at timestamptz not null default now()
);

alter table public.contas_a_pagar_bases enable row level security;

revoke all on table public.contas_a_pagar_bases from anon, authenticated;
grant all on table public.contas_a_pagar_bases to service_role;
```

Não crie política pública de leitura. A aplicação acessa essa tabela somente no servidor com a chave secreta. O conteúdo de `ciphertext` já chega cifrado e é autenticado criptograficamente antes de ser aceito novamente.

## 3. Criar o usuário inicial

1. No painel, abra **Authentication > Users**.
2. Escolha **Add user > Create new user**.
3. Use o e-mail técnico `alan@contasapagar.local`.
4. Informe a senha inicial combinada diretamente com o administrador e marque o e-mail como confirmado.
5. Não escreva essa senha em arquivos, commits ou variáveis de ambiente da aplicação.

Na tela do sistema, o usuário digita apenas `alan`. O backend acrescenta o domínio técnico definido em `SUPABASE_USERNAME_DOMAIN` e o Supabase valida a senha. Para usuários futuros, repita o mesmo padrão: `nome@contasapagar.local` no Supabase e `nome` na tela.

## 4. Gerar a chave da BASE DADOS

Em uma máquina segura, execute:

```bash
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Copie o resultado para um gerenciador de segredos. Essa chave:

- precisa ter 32 bytes aleatórios;
- não é uma senha humana;
- nunca deve entrar no GitHub;
- precisa ser preservada enquanto a BASE DADOS persistida existir;
- não pode ser trocada sem antes migrar/regravar o conteúdo, pois a base anterior deixará de ser descriptografável.

## 5. Configurar o Render

No serviço do Render, abra **Environment** e crie:

| Variável | Valor |
|---|---|
| `SUPABASE_URL` | URL `https://...supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | chave `sb_publishable_...` |
| `SUPABASE_SECRET_KEY` | chave `sb_secret_...` |
| `SUPABASE_USERNAME_DOMAIN` | `contasapagar.local` |
| `PERSISTENT_BASE_KEY_B64` | chave aleatória gerada no passo 4 |

Mantenha as variáveis já existentes de sessão, upload e processamento. O `render.yaml` marca os três segredos como `sync: false`, portanto eles precisam ser informados manualmente no painel.

## 6. Publicar e verificar

1. Faça o deploy pelo fluxo GitHub → Render.
2. Confirme que `/healthz` retorna status `ok`.
3. Abra a URL principal e confirme que o site mostra primeiro a tela de login.
4. Entre com `alan` e a senha criada no Supabase.
5. Abra **Base de Dados**, edite um campo de teste autorizado e salve.
6. Feche o navegador, abra uma nova sessão, entre novamente e confirme que a alteração foi restaurada.
7. No Supabase, verifique que a linha contém somente `ciphertext`, `nonce`, revisão, contagem e horário — nunca fornecedores ou classificações em texto aberto.

## 7. Backup e recuperação

- Guarde a chave `PERSISTENT_BASE_KEY_B64` no gerenciador de segredos da empresa.
- Use **Exportar Base em Excel** para backups operacionais autorizados.
- Restrinja o acesso ao painel do Supabase e do Render com MFA.
- Se a chave de cifra for perdida, o conteúdo persistido não poderá ser recuperado; restaure uma exportação autorizada e grave uma nova base.
- Se uma chave Supabase for exposta, revogue-a no painel e atualize imediatamente o Render.

Referências oficiais:

- https://supabase.com/docs/guides/getting-started/api-keys
- https://supabase.com/docs/guides/database/postgres/row-level-security
- https://supabase.com/docs/guides/database/secure-data
- https://supabase.com/docs/guides/auth/passwords
