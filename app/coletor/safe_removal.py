"""Explicit portable removal preparation. Never removes program files/settings.

Only the existing managed device key and its device-specific authorization are
withdrawn. This command does not create credentials or start login/browser flows.
"""
import sys

from .device_provider import DeviceProvider
from .institutional_access import OFFICIAL_ORIGIN
from .protected_storage import ProtectedStorage
from .instance_lock import CollectorInstance


def run(*, provider=None, output=None):
    output = output or sys.stdout
    provider = provider or DeviceProvider(browser=lambda *args, **kwargs: False)
    print('Remoção segura do acesso deste PC. As configurações e a pasta portátil serão preservadas.', file=output)
    instance = None
    try:
        metadata = getattr(provider, '_metadata', None)
        before = provider.removal_status()
        if metadata is not None and (before or metadata.directory.exists()):
            instance = CollectorInstance(metadata.directory).acquire()
            before = provider.removal_status()
        if metadata is not None: ProtectedStorage(metadata.directory).clear()
        if not before:
            print('Nenhum vínculo local registrado. Nenhuma chave foi verificada ou apagada.', file=output)
            return 0
        try:
            provider.close()  # Explicit command authorizes the existing per-device logout.
        except Exception:
            pass  # Inspect durable state; never echo input, signatures or exception details.
        after = provider.removal_status()
        if not after:
            print('Chave local removida. A retirada remota foi confirmada ou não havia dispositivo vinculado.', file=output)
            print('Você pode remover manualmente a pasta portátil após fechar o Coletor.', file=output)
            return 0
        if after['state'] == 'revokedLocally':
            print('Chave local removida. A revogação remota ainda NÃO foi confirmada.', file=output)
            print('Guarde este identificador público e conclua a retirada deste dispositivo no Ecossistema:', file=output)
            print(after['deviceId'], file=output)
            print(OFFICIAL_ORIGIN + '/frequency-collector/revoke?device=' + after['deviceId'], file=output)
            print('Se apagar o programa agora, nenhuma fila ou conclusão automática é garantida.', file=output)
            print('As configurações e o registro público de saída pendente foram preservados.', file=output)
            return 2
        print('Limpeza local não concluída. Preserve a pasta e tente novamente; nenhuma remoção segura foi confirmada.', file=output)
        return 1
    except Exception:
        print('Não foi possível verificar a limpeza. Preserve a pasta e peça ajuda; nenhum segredo foi exibido.', file=output)
        return 1
    finally:
        try:
            provider.release()  # Free handles only; never erase another key or program folder.
        except Exception:
            pass
        if instance is not None: instance.close()
