# Coletor 0.4: candidato operacional de frequência V2

Implementação para revisão e merge junto do backend Ecossistema. Não equivale a
publicação, configuração produtiva ou validação real de Microsoft/TPM/Smecel.
Os marcos anteriores de prévia continuam úteis como histórico; esta entrega
substitui suas descrições de coleta, agenda e persistência como etapas futuras.

## Operação

Login Ecossistema, autorização nativa da chave Windows, login Smecel diretamente
no Edge, carregar turmas, seleção por nomes e ativar coleta. A agenda vem do
servidor e é compartilhada por escola/ano com revisão CAS. O rascunho local de
desenvolvimento nunca serve como agenda do runtime Windows. Tema, raposa e
seleções sem alunos continuam locais. Sem tarefa ou serviço: o instalador
oferece (marcado) um atalho na pasta Inicializar que abre o Coletor ao lado do
relógio, e a coleta ativa é retomada ao reabrir. Histórico operacional sem
nomes de alunos fica neste PC por 30 dias.

Um processo por perfil do Windows, com lock liberado pelo SO. Um dispositivo
ativo por escola/ano, por concessão do banco; os outros ficam de reserva. Lease
de 120 segundos, heartbeat a cada 30 segundos. Heartbeat reporta e não renova.
Cada turma recebe nova concessão/fencing; se expirar durante a captura, uma nova
lease precede o primeiro envio. Não se renova um lote cuja resposta ficou incerta
sem consultar seu recibo original. Não há coleta sobreposta ou replay de horários
perdidos. IANA vem de tzdata fixado no pacote, inclusive fins de semana opcionais.

Pausa local interrompe o trabalho deste PC; pausa escolar é CAS no servidor.
Sessão Smecel expirada: com o acesso salvo (DPAPI, só leitura pelo worker), o
Coletor entra sozinho uma vez por coleta; senha recusada para a coleta até o
acesso ser corrigido, com aviso ao lado do relógio, sem tentar em loop.
Lista/contexto/ano e diário/URL exatos são revalidados antes de cada captura
(a lista, por até 5 min na mesma sessão enquanto ninguém mais navegou a janela).
Status, concessão, leitura e status pós-leitura de uma turma ficam num único
bloco verificado online na entrada e na saída; o envio abre o seu próprio.
Não se seguem vínculos de alunos para buscar identidade. Contexto observado não
é prova criptográfica de identidade da conta Smecel.

## Transporte e domínio

Contrato autoritativo: `ecossistema-escola/shared/attendance-contracts/frequency-v2.ts`.
O webview não recebe método genérico de envio. Somente o adaptador privado do
worker gera lotes. HTML selecionado, demonstração e prévia manual continuam sem
envio. Cada operação passa pelo gate online antes/depois: autorização, revogação
e Diretório. TLS somente em admin.escolaieda.com, sem redirecionar, cookies ou
proxy ambiental. Frequência tem limite de 16 MiB; APIs antigas mantêm seus limites.

O pedido canônico UTF-8 usa chaves ordenadas, sem espaços, sem ASCII escaping.
SHA-256 base64url vincula todo o payload ao desafio, nonce, destino, purpose e
assinatura CNG. Provas anteriores não ganham campo extra. A versão de observação
é SHA-256 do JSON canônico `{academicYear,sourceClassId,observedAt,htmlSha256,
parserVersion}`; uma reobservação tem versão própria, enquanto retries mantêm
bytes/requestId/version/observedAt idênticos e usam um novo nonce.

O PC manda referências opacas SHA-256 do nome/turma normalizados, ano e classe de origem, nome e turma observados;
nunca escolhe ou envia studentUid. A referência fica estável entre reobservações de mesmo nome/turma, não entre renomeações; homônimos idênticos levam ordinal local e nunca decidem identidade. A decisão central do Ecossistema resolve a
identidade. As seis posições nativas são preservadas. Apenas X/J conhecidos são
esparsos; pontos, desconhecidos, vazios e falhas não viram presença. Cobertura e
roster não são certificados pelo cliente. Captura parcial pode preservar X/J
alinhados e cabeçalhos conferidos, mantendo `complete:false/rosterComplete:false`.
Datas futuras usam o corte civil no fuso da escola. Percentuais e denominadores
permanecem indisponíveis enquanto não houver evidência suficiente no servidor.

## Proteção local

Ativar pergunta em diálogo nativo antes de persistir sessão/fila. Recusar mantém
somente memória. Chromium storage_state transita apenas na pipe privada do worker
e memória; não se cria arquivo JSON/plaintext de perfil autenticado. DPAPI usuário
cifra os dois blobs próprios, com propósito exclusivo, deviceId e generation na
entropia. Chave Microsoft/refresh de servidor nunca vai ao PC.

Fila: no máximo 64 lotes / 64 MiB / sete dias. GC toca só os blobs próprios.
Recebimento confirmado exige receipt servidor; timeout consulta receipt antes
de até três tentativas com backoff limitado. Fencing/CAS alterados não mudam o
lote silenciosamente: o operador descarta e recaptura. Perda de rede cancela
trabalho e navegador; não é recibo de revogação e pode conservar a fila cifrada
consentida para reconciliação. Logout/revogação limpa dados operacionais e blobs;
fechamento encerra processos e retém somente o que foi expressamente protegido.

## Aceite e validação

Suítes existentes preservadas, com novas regressões de hash/purpose, sexta posição,
observação parcial, receipt após timeout, CAS, pausas, lease expirada/takeover,
login expirado sem loop, cancelamento tardio, DPAPI/entropia/corrupção/retensão e
exclusão da segunda instância. Native CI testa runtime embutido, WinForms,
WebView2, Edge isolado e CNG anônimo contra o validador real do backend.
O ZIP só passa pela função de empacotamento após todas as evidências nativas.

Após revisão e merge do responsável: configurar/publicar backend pelas rotas
oficiais, aplicar migrations aprovadas, validar login Microsoft/TPM real, login
Smecel, seleção de turmas, primeira coleta/recibo, reserva/takeover e reabertura
no PC da escola. Nada disso é simulado como homologação produtiva nos testes.
