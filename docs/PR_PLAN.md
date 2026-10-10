# Sequência de revisão

1. Este draft: shell/UI, parser de prévia, fixtures sintéticas, testes e limites.
2. Revisão independente das ambiguidades, fonte incompleta e fronteira de identidade.
3. QA Windows: WebView2, seleção de arquivo, tema, cancelamento, fechamento e
   ausência de persistência. Sem instalador ou registro de dispositivo neste passo.
4. Definir contrato da API e associação à matrícula, com rejeições explícitas.
5. Desenhar captura autenticada e solicitar apenas a autorização necessária para
   acesso persistente. Depois implementar coleta em ambiente de teste isolado.
6. Lease/fencing, idempotência, correções históricas, agendamento, bandeja e portal
   em mudanças separadas, todas em draft para revisão.

Este PR não autoriza merge, deploy, release, publicação de instalador ou escrita
em produção. Nenhum workflow de implantação integra este repositório.

## Limite confirmado em 10/10/2026

Construir a base agora, sem mandar qualquer dado ao PostgreSQL/API. A experiência
dos responsáveis deve ser definida antes de fechar os dados a transmitir.
Nenhum contrato preliminar neste código é aprovação do esquema final.
