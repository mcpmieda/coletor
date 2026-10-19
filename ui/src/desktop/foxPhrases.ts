// What the fox says: short, friendly and rare, like the Atualizador's dragon.
// Random choice without repeating the last few lines.
export type FoxMood = 'idle' | 'running' | 'ok' | 'error' | 'paused' | 'sleep' | 'pet';

const hour = () => new Date().getHours();

const POOLS: Record<FoxMood, (string | (() => string))[]> = {
  idle: [
    () => (hour() < 12 ? 'Bom dia! A frequência está comigo.' : hour() < 18 ? 'Boa tarde! Sigo de olho no Smecel.' : 'Boa noite! Amanhã tem mais chamada.'),
    'Eu entro no Smecel sozinha nos horários da agenda.',
    'Dica: em Tarefas dá para mudar os horários de coleta.',
    'Turma nova no Smecel? Eu pego sozinha.',
    'Só mando faltas e faltas justificadas. Nada além disso.',
    'Minhas orelhas ficam em pé quando chega a hora da coleta.',
    'Psiu… clique em mim.',
    'Dica: em Ajustes dá para ver o navegador trabalhando.',
    'Frequência em dia, raposa tranquila.',
    'Tô aqui, só observando.',
  ],
  running: ['Coletando a frequência…', 'Mãos à obra! Quer dizer, patas.', 'Lendo os diários com carinho.', 'Uma turma de cada vez.'],
  ok: ['Tudo enviado!', 'Prontinho, frequência no Ecossistema.', 'Mais uma coleta concluída.'],
  error: ['Ops… algo deu errado. Dá uma olhada em Registros.', 'Encontrei um problema. Os detalhes estão em Registros.'],
  paused: ['Coleta pausada. Vou tirar um cochilo.', 'Pausada. Me chama quando precisar.'],
  sleep: ['zzz…', '…chamada… diário… zzz'],
  pet: ['Hehe!', 'Obrigada!', 'Isso faz cócegas!', 'Yip! (o bom)', '♥', 'De volta ao trabalho!'],
};

const recent: string[] = [];

export function pickPhrase(mood: FoxMood): string {
  const pool = POOLS[mood].map(p => (typeof p === 'function' ? p() : p));
  const options = pool.filter(p => !recent.includes(p));
  const choices = options.length ? options : pool;
  const text = choices[Math.floor(Math.random() * choices.length)];
  recent.push(text);
  if (recent.length > 6) recent.shift();
  return text;
}
