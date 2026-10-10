# Mascote e bandeja: direção pendente

O usuário pediu um animal bem diferente do dragão do Atualizador, com inspirações
antes da escolha definitiva e ícone na bandeja ao lado do relógio. Nenhum mascote
foi escolhido ou gerado neste marco; o ícone atual é apenas funcional. HeroUI,
e tipografia continuam os mesmos da família de aplicativos. A paleta mudou para
vermelho/bordô por escolha explícita; inspirações do mascote devem acompanhar isso.

A referência fornecida contém pixel art chibi, contorno escuro, olhos legíveis e
paleta curta. O futuro sprite deve ter grade e paleta próprias; não reutilizar o
animal, nome, assets de marca ou estados operacionais do Atualizador por acidente.

## Contrato visual futuro

- Sprite e atlas locais versionados, com proveniência da arte aprovada; nada remoto.
- Mascote discreto, sem cobrir conteúdo ou interceptar cliques externos; opção de
  ocultar e respeito a prefers-reduced-motion. Piscar/respirar sem falsas notificações.
- Ícone simplificado da cabeça em 16, 20, 24, 32 e 48 px, nitidez no Windows e contraste
  claro/escuro. Estado sempre redundante em texto/tooltip, não apenas cor ou animação.
- Estados reais previstos: parado, coleta em andamento, reconexão necessária,
  falha e espera de liderança. Não mostrar “sincronizado” sem confirmação da API.

## Contrato Windows futuro

- Identidade própria na janela/barra de tarefas e tray, independente do Atualizador.
- Menu: abrir painel, coletar agora, pausar/retomar, estado e sair; ações dependem do
  backend real e de autorização. “Sair” deve explicitar que encerra a coleta local.
- Fechar painel e encerrar agente são ações distintas. Minimização na bandeja e
  instância única precisam teste no Windows; não estão implementadas.
- Inicialização automática, tarefa no logon, empacotamento e instalação ficam para
  uma etapa autorizada. Nenhum registro, serviço, tarefa ou instalador foi criado.
- Não copiar certificados, cofre, tokens, perfil Chromium ou nomes internos do
  Atualizador. Segredos futuros ficam no cofre OS somente após aprovação apropriada.

Aceitação futura: tamanhos reais em tela clara/escura, escala125/150%, menu por teclado,
leitor de tela, uma instância só, reinício do Explorer, recuperação de falha e encerramento
limpo. O plano não afirma que bandeja ou animações já funcionem neste protótipo.
