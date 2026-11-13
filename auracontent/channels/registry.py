from auracontent.channels.finance.brain import FinanceBrain
from auracontent.channels.mystery.brain import MysteryBrain

# Chaque chaîne : un Brain (sous-classe de BaseBrain) + config/channels/<nom>.yaml.
CHANNEL_REGISTRY = {
    "mystery": MysteryBrain,
    "finance": FinanceBrain,
}
