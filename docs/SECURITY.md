# Segurança e privacidade

- Nenhuma credencial ou sessão foi criada ou copiada para o projeto.
- Não há rede de saída no backend de domínio; não há cliente PostgreSQL/API.
- HTML importado/capturado não é renderizado na interface privilegiada: apenas
  texto/estrutura permitida entra no modelo. O site fica em Edge separado,
  sem bridge, em contexto sem persistência. [Fronteiras da sessão manual](MANUAL_SESSION_MILESTONE.md).
- Nenhum nome de aluno, corpo HTML ou credencial vai para logs.
- Prévia do diário não é persistida; recarregar/fechar limpa dados da memória da interface.
- Preferências de tema/mascote e agenda sem dados pessoais ficam em JSON validado
  na pasta própria ColetorFrequenciaSmecel do perfil local Windows. A ponte oferece
  somente setters específicos para esses ajustes; não aceita caminho, chave
  arbitrária ou aluno nos setters. A leitura manual tem métodos separados e estreitos.
  No navegador de QA, permanece localStorage. O perfil WebView continua privado/efêmero.
- Gravação atômica mantém o arquivo anterior se a substituição falhar. Arquivo
  inválido produz sugestões e aviso sem log ou backup de seu conteúdo.
- Arquivos reais, perfis Chromium, bancos locais, chaves e instaladores devem
  permanecer fora do Git. .gitignore oferece defesa adicional, não substitui revisão.
- Hash de snapshot garante determinismo/integridade interna; não prova autoria
  da origem, autenticidade de uma matrícula ou autorização de envio.
- MappingValidation é contrato interno futuro. Uma flag ou caixa na UI jamais
  poderá fabricar um comprovante de validação da API.
- Falha, diário incompleto ou símbolo desconhecido não gera deleção nem presença.
- Não há execução automática ao iniciar Windows, serviço ou instalação.
  A bandeja WinForms controla apenas a janela e mostra estados da leitura local.
  Com a coleta ativa, o X esconde a janela; Sair encerra o programa.

Antes de piloto: revisão de ameaça do perfil autenticado, cofre OS, transporte,
revogação de dispositivo, lease/fencing, retenção mínima e controles por aluno;
validação manual do parser em amostra autorizada sem inserir dados reais no Git.

Limites defensivos: 24 MiB de HTML na interface/serviço, 64 fichas, 130 mil
registros, 200 mil nós e diagnósticos agregados por código/ficha. Excesso de
volume descarta a prévia parcial e mantém o envio bloqueado.


A seleção de turmas da versão0.3 usa arquivo separado class-selection.json.
Só contém IDs de turmas,ano/contexto não secreto e revisão. Toda nova sessão e
captura exige listagem atual; escolhas ausentes não são revogadas nem autorizam
leitura. Veja CLASS_DISCOVERY_EVIDENCE.md. Senhas/cookies/tokens continuam fora
das preferências. O acesso Smecel salvo é opcional, cifrado por DPAPI do usuário,
nunca volta à janela (só a conta mascarada) e é apagado ao sair da conta. A origem e o proxy/TLS não foram ampliados.
