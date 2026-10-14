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

## Implementação candidata e validação, 14/10/2026

A branch instala DeviceProvider na ponte desktop e os brokers concretos nas
rotas Pages da PR backend. A abertura do programa não cria chave nem chama login.
A primeira autorização exige backend pronto e confirmação nativa explícita antes
de criar chave Windows. TPM é padrão; Software KSP exige decisão adicional.
A chave privada nunca é exportada. device.json guarda somente identificadores
públicos e estado de limpeza, nunca senha, cookie, refresh ou segredo de polling.

O navegador oficial exige código de seis dígitos mostrado exclusivamente no PC,
checkbox explícito, CSRF, state/nonce exclusivo e PKCE. Microsoft permanece no
navegador; o callback valida o ID token e consulta somente o próprio usuário.
O PC salva os metadados antes de confirmar recebimento; até esse claim o backend
não libera acesso. Pareamentos expirados sem claim revogam seu grant e descartam
o refresh cifrado. As 17 operações da ponte verificam autorização antes/depois.

Reabrir usa a mesma chave após prova online, sem novo login ordinário. Fechar
libera handles/RAM; Sair da conta tenta revogar e apaga a chave local mesmo
offline. Se faltar a confirmação servidor, permanece bloqueado com metadados
públicos e oferece concluir revogação no navegador autenticado. Revogação própria
não depende de Graph nem do refresh estar disponível. Uma falha de limpeza da
sessão de origem não impede tentar apagar a chave institucional.

Revisão interna independente não encontrou achado concreto restante no escopo
sintético após correções de finalidade de revogação, expiração sem claim,
recuperação de exclusão e limpeza independente. CI do SHA final é gate de entrega.
QA Windows usa apenas chave CNG anônima, sem nome, liberada ao final, e os
validadores reais do backend por stdin: pareamento, acesso e revogação. A fixture
compilada, hashes de proveniência e licença Zod ficam fora do pacote desktop.
Ela não comprova TPM, persistência/exclusão de chave real ou ativação humana.

O pacote 0.4.0-teste inclui a entrada protegida, mas a ativação institucional real
continua bloqueada: DDL aguardando readback Deploy to production OFF, binding e
chave dedicada não configurados, merge/deploy e prova tenant não realizados.
O comportamento real de auth_time e User.Read (accountEnabled e marcador de
revogação) ainda requer operador autorizado. Falta/403/null bloqueiam acesso.
Nenhum aluno, envio, credencial persistente real ou permissão Microsoft foi criado.
Remover a pasta não remove chave CNG; use Sair da conta antes de excluir quando
houver ativação. A coleção Smecel permanece separada e envio desativado.
