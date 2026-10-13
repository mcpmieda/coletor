# Marco 1: entrada assistida e leitura manual

Base: `main` após a resolução da auditoria #3. Esta etapa não altera o
Ecossistema, banco, permissões, proteção de branches ou autenticação de dispositivos.
Sonar permanece em uma etapa posterior.

## Fluxo entregue

1. Informe o `ct` numérico e o ano. Preparar valida o escopo sem abrir rede.
2. Confirme a abertura da URL anual conhecida. Um processo separado inicia o
   Microsoft Edge instalado, com sandbox do Chromium e contexto sem persistência.
3. O operador entra diretamente no site. O coletor não recebe senha pela bridge,
   não preenche formulários e não inventa seletores ou endpoints de login.
4. Confira escola, turma e ano na janela do site e autorize a leitura para memória
   local. A URL deve corresponder exatamente ao diário/ct/ano preparados.
5. A leitura clona somente o contêiner documentado, remove formulários, campos,
   scripts, atributos e elementos externos, aplica limites e usa o parser existente.
   Um erro estrutural descarta o resultado parcial. A bridge recebe somente a prévia
   normalizada e evidência local (URL, horário, hash e contagem observada).
6. Encerrar invalida a geração, descarta respostas atrasadas, encerra apenas a árvore
   de processos pertencente à sessão e remove seus temporários. Sair do programa
   também encerra a sessão. Não há retentativa, login ou leitura em segundo plano.

## Fronteiras de segurança

- A página remota nunca entra no WebView privilegiado. A bridge permanece somente
  na interface local; o Edge externo não possui `pywebview.api` nem acesso à bridge.
- HTTPS em `www.smecel.com.br` é a única origem permitida para requisições.
  WebSockets, downloads e popups ficam bloqueados/encerrados. Domínios SSO/CDN
  adicionais não são liberados por suposição.
- Não se reutiliza perfil pessoal, não há CDP/TCP de depuração nem exportação de
  cookies, `storage_state`, credenciais, HTML, HAR, trace ou vídeo.
- O contexto do navegador é não persistente. O navegador e o driver criam
  temporários técnicos próprios no diretório da sessão, removidos ao encerramento.
  Isso não afirma que o sistema operacional nunca escreva buffers ou temporários
  em disco. Uma queda do sistema pode impedir a limpeza normal; não se faz uma
  limpeza global de perfis ou arquivos de outros programas.
- O Job Object do Windows contém o worker antes de liberar a primeira mensagem;
  fechar o job encerra somente seus descendentes. Não se mata Edge/Python por nome.
- Cancelamento mantém o bloqueio da operação até seu término e rejeita gerações
  antigas. Não há ponte pública para executar JavaScript, abrir URL arbitrária,
  selecionar perfil ou trocar o driver. Injeções de fixtures existem apenas no QA Python.
- Prévias não autorizam envio. O bloqueio incondicional, a origem não comprovada,
  identidade não durável e completude não comprovada continuam ativos. As seis
  posições continuam capacidade do diário, sem inventar quantidade de aulas.

## Evidência e limites

A fonte disponível confirma a URL anual e o formato de `div.container-fluid`,
cartões e tabela anual (ver [regras da fonte](SMECEL_SOURCE_RULES.md)). Não confirma
o fluxo de login/SSO atual, marcador autenticado, identidade da escola ou contrato
externo da lista completa. Não se deve chamar esta sessão de autenticação validada.

O QA usa exclusivamente alunos, páginas e valores sintéticos; intercepta todas as
requisições do navegador de teste. Testa consentimento nas duas etapas, escopo,
senha/formulário rejeitado, sanitização, ausência da bridge, origem proibida,
cancelamento e encerramento. O ZIP só é criado após os gates nativos anteriores
e os dois gates novos de sessão manual e Edge externo.

Pendência para acompanhamento autorizado: operador, turma/ano de teste, confirmação
de escola, diário exibido e eventual fluxo/domínio SSO necessário. Nenhum login ou
diário real foi acessado para construir este marco. O pacote `0.2.0-teste` é portátil,
privado, requer Edge/WebView2/.NET 4.8 existentes e não instala nada no computador.

Referências primárias de implementação: [contextos sem persistência](https://playwright.dev/python/docs/api/class-browser#browser-new-context),
[Edge instalado e sandbox](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch),
[Job Objects do Windows](https://learn.microsoft.com/windows/win32/procthread/job-objects).
