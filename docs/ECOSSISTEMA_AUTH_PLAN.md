# Autenticação institucional do Coletor: diagnóstico e decisão pendente

Proposta inicial histórica. O requisito posterior de permanência/renovação e a
inspeção dos grants estão em [DEVICE_AUTH_DECISION.md](DEVICE_AUTH_DECISION.md).
O limite fixo de 4 horas e a recomendação inicial de grants de aplicação não
são mais a proposta preferida. Nenhuma dessas propostas foi ativada.

Estado: preparação de contrato e gate, sem integração ativa, sem pacote novo.
O app 0.3.0 entregue permanece inalterado. Nenhuma configuração produtiva foi lida
com credenciais administrativas ou alterada; nenhum login real foi executado.

## Código oficial verificado

Ecossistema main confirmado em 13/10/2026:
`88edc5d68dd67b00a4ce3f1641ff4afb473fea98`.

- `server/env.ts`: origem produtiva `https://admin.escolaieda.com`.
- `functions/[[path]].ts`: GET `/auth/login`, GET `/auth/callback`, POST
  `/auth/logout`, GET `/api/me`. Não há callback desktop nem endpoint de Coletor.
- `server/auth/oidc.ts`: Web OIDC Entra; authorization code, PKCE S256,
  state/nonce, validação RS256/issuer/audience/tenant/validade no backend;
  redirect registrado é `/auth/callback` no domínio oficial. Credencial Web
  permanece exclusivamente no servidor.
- `server/auth/session.ts`: cookie `__Host-ecossistema_session`, cifrado/validado
  pelo servidor, expiração. `session-policy.ts`: duração 4/8/12 horas.
- `/api/me` retorna authenticated, identityKey, expiresAt, name, roles,
  capabilities. Não retorna autorização específica de Coletor nem confirmação
  de revogação. Papéis vêm dos grupos no momento do login; o endpoint não
  reconsulta grupos, conta bloqueada ou revogação Entra durante uma sessão.
- `server/auth/capabilities.ts`: capacidades administrativas existentes; nenhuma
  `frequency.collector.use`. Reutilizar `gradebook.persistence.admin` como
  autorização do Coletor confundiria escopos e não foi feito.

Documentação Microsoft consultada em 13/10/2026:
[revogação de acesso](https://learn.microsoft.com/en-us/entra/identity/users/users-revoke-access).
O cookie emitido pelo app não é automaticamente revogado pelo Entra; a aplicação
precisa aplicar a própria política. Consultar `/api/me` repetidamente não elimina
essa limitação da implementação atual.

## Proposta mínima para aprovação do responsável

1. Política **nova**, explícita e restrita ao Coletor: capability proposta
   `frequency.collector.use`, atribuída no backend ao papel institucional
   `ADMINISTRADOR` já existente. Outros papéis não recebem acesso por inferência.
   Sem lista piloto de pessoas/turmas, sem ativação de contas, sem decisão por
   dados de alunos. Esta política ainda NÃO foi aplicada.
2. Login reutiliza a URL oficial `/auth/login` num Edge separado sem bridge e
   contexto efêmero. Callback e troca de código continuam no servidor existente.
   Não requer por si só novo cliente Entra, redirect desktop, segredo ou consent.
   Senhas/cookies/tokens não atravessam a bridge nem são persistidos pelo Coletor.
3. Endpoint **proposto, ainda inexistente** GET
   `/api/frequency-collector/access`: reutiliza requireAuth, exige a nova
   capability no servidor e uma fonte autoritativa de revogação definida abaixo.
   Não recebe nome, papel, aluno, turma ou permissões escolhidas pelo cliente;
   não transfere dados acadêmicos; resposta no-store, tamanho máximo 8 KiB.
4. Decisão necessária sobre revogação: implementar uma autoridade específica
   de acesso/sessões do Coletor no backend, revogável sem invalidar contas ou
   sessões de outros módulos. A mudança deve definir armazenamento, comando
   administrativo já autenticado, proveniência e eventual migration/binding.
   Bloqueio/removal de grupo no Entra precisa também de fonte sincronizada ou
   leitura institucional autorizada, com prazo de propagação declarado. Não
   inventar promessa de revogação imediata a partir do cookie atual.
   Inspecionar grants efetivos e escolher a permissão mínima antes de propor
   qualquer consent; não reutilizar tokens Operations/Maintenance no app.
5. Após contrato/política/fonte de revogação aprovados: implementar transporte
   privado, UI de login e proteção de TODAS as funções de coleta, seleção,
   prévia, importação e configurações na bridge Python. Cancelar/destruir
   sessão Smecel e prévias ao negar acesso, expirar, trocar conta ou sair.
   Apenas status/login e encerramento seguro ficam públicos. Sem uso offline.
6. Executar testes negativos/positivo sintético, QA Windows real do pacote,
   CI do SHA final e revisão independente. Produção só passa a ser testável
   depois de endpoint e configuração necessários estarem publicados pelo
   responsável conforme autorização própria. Não fazer merge/deploy por esta
   preparação. Não entregar pasta nova como pronta antes disso.

## Contrato candidato revisável

`app/coletor/institutional_access.py` é independente e NÃO está instalado na
DesktopApi nem na interface. Nenhum provider produtivo está configurado. A URL e
capability propostas são constantes documentadas, não endpoints reais descobertos.

Resposta candidata para autorização online:

```json
{
  "contractVersion": 1,
  "authenticated": true,
  "authorized": true,
  "capability": "frequency.collector.use",
  "identityKey": "opaque-session-identity",
  "expiresAt": "2026-10-13T23:00:00Z",
  "checkedAt": "2026-10-13T22:59:00Z",
  "revocationChecked": true
}
```

O backend só pode emitir `revocationChecked:true` após consulta real à autoridade
aprovada. Não adaptar `/api/me` preenchendo essa propriedade artificialmente.
O transporte futuro autentica TLS/origem exata, não segue redirect de API,
mantém cookie apenas no contexto efêmero e constrói OnlineResponse no Python,
nunca a partir de argumento JS ou JSON da UI.

O gate verifica autorização online em cada comando e novamente antes de devolver
resultado; descarta resultado tardio após logout/revogação/troca de identidade.
Falhas, ausência de provider, documento malformado, resposta excessiva,
capacidade incorreta e prova vencida/stale bloqueiam. Não há cache de autorização.
O marcador `revocationChecked` não é criptografia nem prova autossuficiente:
depende do transporte TLS e da implementação correta do backend.

Regressões: `tests/test_institutional_access.py`, 12 testes sintéticos aprovados.
Ruff E9/F63/F7/F82 aprovado. Isso valida o gate candidato, não autenticação real
ou cobertura da bridge/UI ainda não integradas. Não há novo smoke Windows.
