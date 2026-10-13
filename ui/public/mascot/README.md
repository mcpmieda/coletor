# Arte aprovada da raposa

Identidade escolhida pelo usuário: raposa vermelha, distinta do dragão do Atualizador.
Base visual gerada por imagem e convertida em código pixel art com autorização
explícita. Sprite em grade64×64, paleta curta e alpha binário; cabeça32×32.

O código-fonte de pixels, paleta e posições está em `ui/src/mascot/sprite-source.json`.
`python scripts/render_mascot_atlas.py` reconstrói estes PNGs com Pillow (validado
com12.3.0; dependência apenas do utilitário de arte, não do aplicativo/parser).
A animação do painel muda o recorte do mesmo atlas, sem trocar src nem buscar
imagens remotas. Os ICOs prontos ficam em `app/assets/fox-icons/`.

A normalização preservou os oito desenhos aprovados: idle, blink, ears, curious,
tail-left, tail-right, sleep e happy. A cabeça possui neutral, blink, attentive,
resting e alert. Não há imagens de alunos ou dados de produção nestes arquivos.

A bandeja permanece opt-in não iniciada: existir um ícone não comprova atividade,
conexão, coleta ou sincronização. Confira `docs/MASCOT_TRAY_PLAN.md`.
