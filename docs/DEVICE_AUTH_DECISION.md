# Vínculo de dispositivo do Coletor: candidato sem ativação

Requisitos recebidos em 13/10/2026: ADMINISTRADOR confirmado; acesso limitado ao
Coletor; evitar login recorrente; preparar permanência segura neste computador.
Ativação real da persistência/configuração ainda exige aprovação específica.
Enviar frequências é a finalidade, mas envio real segue desativado e fora desta
preparação. Login Smecel é separado e sua validade externa não é controlada aqui.

## Grants verificados somente por leitura

Consulta em 13/10/2026,23:25 UTC, usando sessão Azure CLI já existente, no tenant
correto. Nenhum token foi impresso ou substituído; nenhum consent/grant foi criado.

- Service principal Graph Backend: somente um application grant Microsoft Graph,
  Sites.Selected. Paginação completa, sem nextLink.
- Service principal Web: único consentimento delegado AllPrincipals consultado
  contém openid profile email. Sem User.Read. Paginação completa.
- Portanto User.Read.All e GroupMember.Read.All NÃO estão presentes no Graph
  Backend. A identidade de Operations não foi usada para contornar negações.
- Auditoria Operations38439648255 passou, mas seu resumo público não enumera os
  grants do Backend; a conclusão acima vem da consulta real a appRoleAssignments.

## Menor escopo de diretório a avaliar

Não ampliar Graph Backend para ler usuários/grupos de todo o tenant. Alternativa
preferida: User.Read DELEGATED no fluxo Web exclusivo de autorização do Coletor,
com chamadas backend /me e /me/checkMemberGroups. Esta última verifica apenas o
GROUP_ADMIN_ID existente e tem User.Read como mínimo documentado para o próprio
usuário. Não usar /directoryObjects nem /users de terceiros.

O app desktop nunca recebe esse token Graph. Para renovação sem novo login, o
backend precisa de offline_access no fluxo de autorização exclusivo do Coletor
e guardar seu refresh token cifrado no servidor, separado do token do dispositivo.
Isso é uma dependência real de consent/armazenamento, ainda não aprovada/ativada.
Não alterar os scopes de login de outros módulos nem seus grants existentes.

Importante: refresh token Microsoft é vinculado a usuário+clientId, não a um
recurso, tenant ou módulo. Marcar o fluxo como Coletor não o restringe no Entra.
O token permanece somente no backend; isso protege o desktop, não transforma o
refresh token servidor em uma credencial collector-only. Atualmente o Web só tem
os grants OIDC observados. Reutilizar esse client exige allowlist fixa de tenant,
issuer, client, Graph/User.Read e chamadas próprias, além de detectar novos
consents antes de ativar uso mais amplo. Não permitir scopes/URLs do cliente.
Isolamento por clientId exigiria App Registration confidencial separado, redirect
e credencial próprios no servidor: alternativa que NÃO foi aprovada/configurada.

Refresh Microsoft pode devolver token novo sem invalidar o antigo. Guardar só o
mais recente com versão/CAS evita concorrência no nosso serviço, mas não comprova
replay detection Microsoft nem revogação do anterior. Excluir o ciphertext local
ou sair do Coletor também não revoga tokens Microsoft previamente copiados.
Revogação do vínculo próprio bloqueia emissão/uso das licenças do Coletor; não
executar revokeSignInSessions global, que atingiria acessos de outros módulos.

Armazenamento servidor candidato: AEAD com propósito e additionalData vinculados
a tenant/client/account/registro/versão, acesso restrito ao broker de renovação,
sem logs/retorno de tokens, transações para substituir o valor e descarte ao
encerrar o vínculo. SESSION_SECRET/seal atual não possui essa separação de
propósito/AAD; não copiar seu formato sem adaptação/revisão. Separação criptográfica
de propósito não isola comprometimento do segredo raiz ou do runtime inteiro.
invalid_grant/interaction_required, identidade/audience/tenant divergentes ou
propriedades negadas/ausentes suspendem o acesso e exigem o caminho legítimo.

A autorização inicial exige transação Coletor ligada à chave/nonce e identidade
validada no fluxo OAuth oficial, seguida de verificação própria atual. Cookie
Web antigo e papel armazenado não são prova nova de diretório/revogação. O tempo
de origem deve vir do fluxo validado; não fabricar origem recente renovando
timestamp local. Revalidação não muda a conta/tenant originalmente vinculados.

Fonte: [refresh tokens Microsoft](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens).

Antes de ativar, um teste autorizado deve confirmar que User.Read permite obter
as propriedades próprias accountEnabled/signInSessionsValidFromDateTime exigidas
pelo contrato. A documentação geral de GET /me é User.Read; não há comprovação
produtiva dessas propriedades neste fluxo, pois não houve consent/login real.
Se faltarem direitos/propriedades, bloquear e devolver decisão; não ampliar para
User.Read.All, GroupMember.Read.All ou qualquer escrita automaticamente.

Fontes oficiais consultadas em 13/10/2026:
[GET usuário](https://learn.microsoft.com/en-us/graph/api/user-get?view=graph-rest-1.0),
[checkMemberGroups](https://learn.microsoft.com/en-us/graph/api/directoryobject-checkmembergroups?view=graph-rest-1.0),
[User.Read](https://learn.microsoft.com/en-us/graph/permissions-reference#userread).

## Dispositivo e renovação propostos

1. Uma confirmação no navegador oficial vincula conta autorizada e chave pública
   do computador. O cookie Web continua apenas no navegador; senha, cookie,
   token Graph/Entra e certificado backend não são copiados ao Coletor.
2. Chave ECDSA P-256 CNG persistida para o usuário Windows, não exportável e
   somente para assinatura. TPM é o padrão candidato. Sem TPM, escolha explícita
   revisada de Software KSP protegido pelo Windows; nenhuma queda automática.
   Não armazenar bearer/refresh token durável em JSON ou junto da pasta portátil.
3. Backend registra public key, conta, grant collector-only e revogação. A chave
   privada não autoriza outras APIs. Nenhum token amplo Ecossistema/Graph no app.
4. Desafio servidor de uso único, validade60s, vinculado a deviceId,processSession,
   finalidade/rota/audience e geração; assinatura com separação de domínio.
   Consumo atômico do nonce antes de emitir uma licença curta (proposta5min),
   vinculada à mesma chave. Reutilização/replay é negado; não existe refresh
   bearer eterno. Ao vencer, nova prova de posse renova silenciosamente.
5. Cada operação/renovação verifica a revogação local no backend. A verificação
   de diretório proposta pode ser compartilhada por conta por até5min, com
   instante/validade explícitos no contrato; depois disso, falha Graph bloqueia.
   Esta janela é uma mudança em relação à proposta de consultar cada comando e
   precisa ser aprovada. Remoção/bloqueio Entra seria detectado até essa janela
   mais a propagação Microsoft; não prometer instantaneidade.
6. Não exigir novo login por limite rígido de4h: renovar enquanto vínculo e
   autorização forem válidos. Revogação, perda da chave ou exigência do provedor
   podem exigir nova autorização. Reabrir o programa usa a mesma chave, após
   confirmação da persistência pelo responsável. Fechar só libera handles/RAM.
7. Sair da CONTA revoga vínculo servidor e remove a chave local. Se offline,
   apagar a chave local impede renovação, mas o servidor precisa marcar a
   revogação quando houver conectividade/administração; licença curta limita
   credenciais já emitidas. Não prometer apagar vínculo servidor sem rede.
8. Remover pasta portátil não remove chave CNG. Precisamos de ação explícita
   Desconectar este computador e desinstalador/removedor que execute a limpeza.
   A atualização de pasta preserva a chave; não confundir atualizar com sair.
9. Formatar/perder chaves requer nova autorização. Restaurar uma imagem completa
   do mesmo Windows/TPM pode restaurar acesso; não há promessa universal de
   detectar todo restore. Rotação/revogação servidor protege contra cópias
   antigas, mas não torna todo backup do sistema distinguível automaticamente.

CNG protege exportação/cópia simples, não comprometimento do usuário/processo.
Chave pública não é segredo; assinatura não prova software intacto. Proteções
backend são necessárias. Revalidação de Smecel continua independente.

## Custo e revogação local

Proposta antiga: 2 queries Graph x 2 verificações por comando = 4 queries por
comando, mais 240queries/h por usuário no heartbeat30s, fora aquisição de tokens.
Proposta de janela5min: até24queries/h por conta ativa para os dois checks,
compartilhadas entre dispositivos/comandos. Batch reduz viagens HTTP, não a
contagem/cota das duas subconsultas. Reutilizar access token backend durante sua
validade evita trocar certificado/token a cada query; isso não cacheia permissão.

Revogação própria do Coletor é simples: registro device com revokedAt/generation;
consulta transacional em cada operação. Sem invalidar sessões de outros módulos.
Só isso, porém, NÃO detecta remoção de grupo/bloqueio Entra automaticamente; essa
limitação não pode ser escondida para eliminar consultas de diretório.

## Preparação de código e testes

windows_device_key.py é adaptador candidato privado, ainda sem ligação à UI,
bridge ou backend. Criação exige activation_authorized Python-only; padrãonega.
Não cria key por load, não sobrescreve key existente, valida políticas no load,
exporta apenas ECCPUBLICBLOB, assina SHA256 domain-separated em modo silencioso.
close não apaga; forget exige remoção explícita e apaga somente a chave gerenciada.

10 testes com FakeCrypto aprovados, sem chamar CNG nem criar credencial real.
QA Windows de Software KSP com chave efêmera NULL-name passou: assinatura
P-256/P1363 validada pelo Node, desafio alterado rejeitado e exportação privada
negada. Não foi criada chave persistente nem vínculo/credencial de conta.
TPM/armazenamento persistente não foram testados. Ainda falta validar segurança
do desafio/nonce e emissão/renovação/revogação server. O gate anterior
tem12regressões; ambas preparações permanecem sem ativação.

Fila de envio: planejar idempotencyKey/snapshot autorizado e confirmação backend
antes de remover item. Não implementar fila com dados reais/pessoais sem contrato
e escopo próprios. Nenhum envio, aluno, consent, chave persistente real, migration,
merge, deploy ou pacote autenticado foi produzido por esta preparação.

## Ponte e tela de entrada, 14/10/2026

O gate agora protege as 17 funções de uso na ponte Python antes e depois da
operação. Somente status/login/logout e limpeza de sessão permanecem acessíveis
sem autorização. A janela desktop mostra a entrada no Ecossistema antes de montar
a interface principal. Ao sair, remove a interface e ignora consultas tardias;
a autorização da UI não substitui a verificação Python. O modo de desenvolvimento
loopback continua separado; ele não é um login institucional.

O provedor real permanece ausente: o padrão mostra ACCESS_NOT_CONFIGURED e
nega operações. Nenhuma chave persistente é criada pela janela nem por iniciar
o programa. Esta branch ainda não oferece um pacote autenticado utilizável.

Validação local: 180 testes Python; 63 testes UI; lint/tipos/build aprovados;
QA visual com Edge instalado e ponte sintética aprovou bloqueio antes de ler
preferências, ausência de campo de senha, entrada autorizada simulada e descarte
de resposta tardia após sair. Evidência: artifacts/institutional-ui/results.json.
Esse QA não comprova Microsoft, permissão real ou autorização nativa.

Os scripts Windows existentes recebem a fixture por parâmetro Python exclusivo
de QA, definido fora do pacote. Não existe flag de ambiente/CLI nem função JS
para liberar o gate. CI cobre também a base da PR empilhada e a regressão visual.
As provas Windows deste SHA serão exigidas antes de declarar o pacote pronto.
