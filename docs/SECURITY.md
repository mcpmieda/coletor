# Segurança e privacidade

- Nenhuma credencial ou sessão foi criada/copied para o projeto.
- Não há rede de saída no backend de domínio; não há cliente PostgreSQL/API.
- HTML não é renderizado: apenas texto/estrutura permitida entra no modelo.
- Nenhum nome de aluno, corpo HTML ou credencial vai para logs.
- Prévia não é persistida; recarregar/fechar limpa dados da memória da interface.
- Só preferência de tema pode ficar no armazenamento local do navegador de QA.
  No launcher desktop, o perfil é privado/efêmero.
- Arquivos reais, perfis Chromium, bancos locais, chaves e instaladores devem
  permanecer fora do Git. .gitignore oferece defesa adicional, não substitui revisão.
- Hash de snapshot garante determinismo/integridade interna; não prova autoria
  da origem, autenticidade de uma matrícula ou autorização de envio.
- MappingValidation é contrato interno futuro. Uma flag ou caixa na UI jamais
  poderá fabricar um comprovante de validação da API.
- Falha, diário incompleto ou símbolo desconhecido não gera deleção nem presença.
- Não há execução automática ao iniciar Windows, serviço, bandeja ou instalação.

Antes de piloto: revisão de ameaça do perfil autenticado, cofre OS, transporte,
revogação de dispositivo, lease/fencing, retenção mínima e controles por aluno;
validação manual do parser em amostra autorizada sem inserir dados reais no Git.
