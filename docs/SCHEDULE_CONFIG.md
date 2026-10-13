# Agenda escolar: base editável, sem execução

## Implementado neste marco

- Configuração prévia em React, padrão America/Bahia confirmado na conversa.
- Horários derivados exclusivamente da proposta sanitizada HORARIO 2026.xlsb,
  versão 75, data interna 22/06. `schedule-presets.json` conserva o SHA da fonte.
- Dez pares dia/turno de segunda a sexta: fim de aula + 10 minutos. Rechecagem
  12:15 no matutino e 18:30 no vespertino, inclusive sexta. Quatro pares de sábado
  e domingo iniciam vazios e desmarcados; o usuário pode editá-los.
- Campos de horário, rechecagem, dia selecionado e fuso editáveis; restauração dos
  padrões e descarte de alterações. Rascunho preservado ao navegar entre páginas.
- Validação HH:MM, no máximo 16 coletas por dia/turno, sem duplicatas, rechecagem
  posterior às coletas, 14 pares únicos, fuso IANA reconhecido.
- A janela Windows salva agenda, tema e preferências da raposa em
  `%LOCALAPPDATA%/ColetorFrequenciaSmecel/settings.json`, independente do Atualizador.
  O JSON tem esquema e limite de 16 KB; a escrita usa temporário na mesma pasta,
  flush/fsync e substituição atômica. Os setters nativos aceitam somente os campos
  próprios de cada preferência. Fuso IANA é validado semanticamente pelo Intl da UI;
  o backend valida formato, tamanho e estrutura sem instalar banco de fusos.
- A prévia no navegador continua usando localStorage da origem local, na chave
  `coletor-smecel.schedule-preview.v1`. Não há endpoint HTTP para gravar arquivos.
- O perfil do WebView permanece privado e efêmero. Nenhum diário, aluno, senha,
  token, cookie ou sessão é persistido. Falha de armazenamento é visível e mantém
  o rascunho; o aviso de salvo só aparece após confirmação da escrita.
- Arquivo inválido usa sugestões e aviso. Não há cópia de seu conteúdo inválido;
  somente salvar explicitamente substitui o arquivo por configurações válidas.
  O teste Windows cobre salvar, fechar, reabrir, restaurar/reabrir e corrupção
  controlada em pasta temporária própria, com sentinela de outro aplicativo intacta.
- Zero relógio operacional, timers de coleta, chamadas externas, autenticação,
  cadastro de dispositivos, fila ou envio. Selecionar um dia não ativa tarefa.

## Contrato preliminar

`schemaVersion: 1`, `scope: school`, `storageMode: local-preview`, `localRevision`,
`sharedRevision: null`, fuso e regras. A revisão é só do rascunho local e não deve
ser promovida a revisão de servidor. Não há schoolId ou identidade inventada.
Somente a ponte local da janela Windows aceita esse documento para armazenamento
local. Não há API de produção ou sincronização que o aceite neste marco.

No produto futuro, a configuração pertence à escola autenticada e é compartilhada
pelos usuários e computadores autorizados, em quantidade variável. Uma alteração autorizada
vale para todos, e o login traz a última versão escolar. Credenciais e sessão
continuam individuais. A autoridade de escola/usuário será a API, nunca o cliente.
O contrato não fixa quantidade de usuários ou dispositivos. Continua previsto um
coletor ativo por vez, com os demais computadores autorizados como reservas;
a quantidade variável não concede acesso nem altera as regras de autorização.

Persistência compartilhada, autorização, auditoria, versão de servidor e edição
concorrente precisam implementação separada: leitura com revisão, escrita com
precondição, conflito visível sem sobrescrever silenciosamente, atualização nos
outros PCs e confirmação ao usuário. Uma mudança de agenda não concede lease nem
escolhe líder; apenas o agente com lease/fencing válido poderá coletar. Essas regras
não estão executando e não fixam o contrato de frequência para responsáveis.

## Limites das fontes

A vigência da planilha não foi atestada. Os horários são gatilhos, não denominador
letivo. Cinco ou seis aulas na grade não autorizam remover a sexta posição nativa
Smecel; a máscara elegível continua dependente do coletivo, calendário e cobertura.
Não inferir dia letivo por checkbox, dia da semana ou evento genérico. Ver
[regras observadas da origem](SMECEL_SOURCE_RULES.md).

Antes da automação: confirmar vigência, calendário/exceções, política de retries,
compensação de horários perdidos, login expirado, fuso na mudança de data e eleição
do líder. Abrir/coletar/fechar navegador, Coletar agora e Pausar são etapas futuras.


## Concorrência local da janela Windows

Gravações usam lock interprocessual do SO em `settings.lock` (sidecar sem dados
acadêmicos/segredos) e substituição atômica de `settings.json`. A agenda enviada
precisa ter `localRevision` exatamente uma unidade acima da salva; uma edição
obsoleta recebe `SCHEDULE_REVISION_CONFLICT`, sem sobrescrever o arquivo.
O operador pode recarregar e descartar suas alterações para partir da revisão
atual. O lock persiste no disco para evitar corrida entre nomes de arquivos;
o SO libera a trava no encerramento/crash. Se a aquisição falhar, não há gravação.
Essa proteção não cria sincronização entre computadores e não transforma o
localStorage do navegador em armazenamento compartilhado transacional.
