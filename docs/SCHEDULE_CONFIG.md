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
- Salvamento somente no localStorage da origem local, na chave própria
  `coletor-smecel.schedule-preview.v1`. Só campos permitidos são serializados.
  Falha de armazenamento é visível. Nenhum diário, aluno ou segredo é salvo.
- A janela desktop usa perfil privado: persistência após fechá-la não é garantida.
  O teste de persistência cobre recarregar a mesma origem no navegador de QA.
- Zero relógio operacional, timers de coleta, chamadas externas, autenticação,
  cadastro de dispositivos, fila ou envio. Selecionar um dia não ativa tarefa.

## Contrato preliminar

`schemaVersion: 1`, `scope: school`, `storageMode: local-preview`, `localRevision`,
`sharedRevision: null`, fuso e regras. A revisão é só do rascunho local e não deve
ser promovida a revisão de servidor. Não há schoolId ou identidade inventada.
Nenhuma API aceita esse documento neste marco.

No produto futuro, a configuração pertence à escola autenticada e é compartilhada
pelos três usuários autorizados e seus computadores. Uma alteração autorizada
vale para todos, e o login traz a última versão escolar. Credenciais e sessão
continuam individuais. A autoridade de escola/usuário será a API, nunca o cliente.

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
