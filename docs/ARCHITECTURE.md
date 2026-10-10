# Arquitetura e limites do primeiro marco

## Decisão de stack

O Atualizador de Planilhas 1.3.0 foi inspecionado em modo leitura (main.py,
api.py, ui/src/App.tsx, ui.tsx, theme.ts e index.css). Ele usa Python, pywebview
com ponte window.pywebview.api, React e HeroUI v3. O coletor segue esse padrão:

- Python 3.12+ para o domínio, sem dependências de rede no parser.
- pywebview/Edge Chromium para a janela Windows, com perfil privado efêmero.
- React 19, HeroUI 3.2.6 e Tailwind 4 para o painel.
- Após pedido explícito, a marca usa bordô #a32743 no claro e vermelho claro
  #f28ba0 no escuro. Mantém Segoe UI Variable Text / Segoe UI e HeroUI do Atualizador.
- Identidade própria, sem reutilizar dados, mutex, instalação ou serviço do Atualizador.

A implementação anterior foi referência de arquitetura/identidade. Não copiamos
empacotador, certificados, senhas, instaladores, macros ou dados operacionais.

## Fronteiras

1. Interface local recebe HTML por seleção explícita de arquivo.
2. PreviewApi expõe somente load_demo e preview_html. Ambos são somente leitura.
3. Serviço valida tamanho/escopo e entrega HTML ao parser sem executar scripts.
4. Parser produz snapshot com posição de aula, estado e símbolo de origem.
5. Validador mantém o envio bloqueado sem identidade/completude verificadas.
6. Interface exibe diário em memória. Agenda sem dados pessoais pode ser salva
   no localStorage como rascunho local versionado. Não existe endpoint ou método de envio.

O servidor HTTP é exclusivamente um adaptador de desenvolvimento/QA. Só escuta
127.0.0.1; exige Host correto, Origin local em POST, JSON e limite de corpo;
rejeita traversal; responde sem cache. O launcher desktop usa a ponte pywebview.

## Modelo da origem

O diário anual nativo fornece fichas de aluno, grade FEV–DEZ, dias 1–31 e seis
posições por célula. Não fornece MAT, studentUid, ct ou total esperado de fichas
como evidência estruturada do documento. Um índice local de ficha não é identidade.

A marca • significa “Aula prevista/presença”: é ambígua. Célula vazia, dia não
letivo, fora da matrícula e falha de captura nunca significam presença.

A captura futura precisa envelope validado com URL autorizada, turma/ano,
contagem/escopo esperados, instante e hash. HTML isolado só gera prévia. Mesmo
um parser estruturalmente bem-sucedido não comprova integridade do relatório.

## Caminho futuro (não implementado)

- Login inicial no Ecossistema e registro de dispositivo, após aprovação de
  acesso persistente; autenticação Smecel separada em perfil Chromium exclusivo.
- Credenciais em cofre do sistema operacional, sem tokens em código/logs/repo.
- Execução da agenda configurável por horários e dias da semana, com fuso IANA.
  A tela de edição e os padrões da versão 75 já existem como prévia local. São gatilhos de coleta, não prova de que uma aula ocorreu.
  No horário configurado, apenas o PC líder abre Chromium exclusivo, verifica a
  sessão, captura, fecha e reporta. Prever Coletar agora, Pausar e tentativas
  espaçadas, com uma coleta por vez e sem replay descontrolado de horários perdidos.
  Login expirado vira reconexão assistida, sem loop de autenticação. Nada disso
  está executando neste marco. Calendário escolar continua sendo fonte separada
  para elegibilidade das aulas e limite temporal do cálculo.
- Quantidade variável de usuários e computadores autorizados, com um coletor
  ativo por vez e os demais computadores autorizados como reservas. O cliente
  não fixa um limite de dispositivos nem concede permissões. API concede lease curto usando seu relógio;
  cada concessão aumenta fencing token. API rejeita token vencido/antigo,
  inclusive depois de reinício, atraso de rede ou retorno do antigo líder.
- Fila local criptografada somente após desenho/aprovação de retenção. Resposta
  incerta exige reconciliação por idempotency key antes de repetir.
- Mudanças propostas pelo coletor; API valida escopo, roster, autorização,
  completude, versões, lease e idempotência antes da transação PostgreSQL.
- Releitura histórica em janelas e reconciliação de correções. Remoção de marca
  em uma releitura não apaga automaticamente um registro anterior: exige uma
  operação explícita e validada de correção, com proveniência/versionamento.
- Portal consulta apenas dados sincronizados e autorizados para aquele aluno,
  com coletado_em/sincronizado_em e status de atualidade separados.
- Bandeja, minimização, recuperação de falhas e instalação por usuário somente
  depois de testes reais em Windows e decisão explícita de distribuição.

## Não é prova de produção

Fixtures são inteiramente sintéticas. CI e testes não fazem login Smecel, não
registram dispositivo, não consultam dados de menores e não tocam no PostgreSQL.
A UI não afirma “conectado” nem mostra sincronização bem-sucedida simulada.

## Horário de coleta não é denominador de frequência

As seis posições do parser são as seis colunas/slots visuais da fonte, não uma
suposição de seis aulas realizadas todos os dias. A planilha de horários pode
sugerir gatilhos diferentes por dia/turno e precisa de vigência confirmada.
Não cortar automaticamente a sexta posição nem mudar a fórmula da frequência
por divergência com essa planilha. A conciliação entre grade, calendário e
semântica nativa permanece uma decisão funcional antes da integração.
