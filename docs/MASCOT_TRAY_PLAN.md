> Atualização: a bandeja da prévia está integrada via WinForms, com estados reais locais. Consulte TRAY_IMPLEMENTATION.md; os trechos sobre adaptador pywin32 abaixo registram o plano anterior.

# Raposa vermelha do coletor

O usuário escolheu a raposa vermelha da prancha de inspirações e pediu um repertório
de animações maior, mantendo o padrão HeroUI com marca bordô/vermelha. Esta é uma
identidade própria; nenhum sprite ou animação de chama do dragão foi copiado.

## Painel implementado

Quadros próprios para idle, blink, ears, curious, tail-left, tail-right, sleep e
happy, em atlas único 256×128, quadros 64×64 exibidos em 128 px. O src da imagem
não muda ao animar; só muda o recorte CSS. A UI os encadeia em piscar, mexer orelhas/cauda, olhar curioso, descansar,
acordar e reagir ao carinho. CSS translate acrescenta respiração, pulinho, passeio
curto, aviso discreto e coração, sem deformar ou espelhar a arte.

As únicas reações de trabalho ligadas neste marco são leitura da prévia, revisão
e erro local. Não há pose de “sincronizado” ou “coleta concluída”. Descanso do
mascote não representa pausa de um coletor: nenhuma coleta está agendada.

- Área própria na barra lateral; não cobre controles ou intercepta cliques externos.
- Botão de carinho acessível por teclado; legendas curtas sem fala automática ou som.
- A raposa fica sempre visível; não há preferências para ocultar ou parar.
- Movimento reduzido deixa uma pose estática; não apenas uma animação CSS mais rápida.
- Timers desligados com movimento reduzido, aba oculta ou sidebar fora
  do layout móvel. Um único timer de cada vez; não usa laço requestAnimationFrame.
- Quadros de gesto no máximo a cada 160 ms; leitura a cada 400 ms. Entre gestos há descanso
  de 1,8–3,6 s; cochilo após 2 min sem interação. A simulação unitária limita callbacks;
  isso não substitui medição de CPU no computador Windows real.
- Clear/Cancel ou erro no diário não modifica agenda, dados ou credenciais.

## Bandeja preparada, ainda não ativada

O módulo opt-in tem estados idle/working/paused/error, cadência limitada e
recuperação após Explorer reiniciar. Ícones distinguem atividade, pausa e erro por
selos e texto, além da cor. Todo tooltip identifica prévia local e automação inativa.

O launcher atual não inicia esse adaptador. Os testes em Linux usam doubles e não
provam Shell_NotifyIcon real, menu nativo, DPI ou limpeza de handles no Windows.
Veja o [contrato da bandeja](TRAY_IMPLEMENTATION.md) para arquivos, fallbacks e QA.

Não foram criados registros, tarefas de inicialização, serviço, instalador ou
acesso persistente. A integração real ao ciclo de vida da janela e ao agente requer
um teste Windows separado; não há controle operacional falso na interface.

## Validação e próximas etapas

Fixtures sintéticas, teste de preferências e reação ao carinho, transição de
reduced-motion e screenshots de todas as páginas nos dois temas. A arte deve
passar pela conferência visual em 128 px e ícones 16/20/24 px antes de publicação.

Depois: testar janela/bandeja real no Windows, escala 125/150%, teclado, Explorer
reiniciado, encerramento limpo, alteração das preferências e política operacional
quando o agente real existir. Não tratar os contratos de animação como autorização
de login, coleta, implantação ou envio de frequência.

