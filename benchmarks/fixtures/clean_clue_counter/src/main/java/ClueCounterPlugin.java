package com.fixture.cluecounter;

import com.google.inject.Provides;
import javax.inject.Inject;
import java.util.EnumMap;
import java.util.Map;
import net.runelite.api.events.ChatMessage;
import net.runelite.api.ChatMessageType;
import net.runelite.client.config.ConfigManager;
import net.runelite.client.eventbus.Subscribe;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;

@PluginDescriptor(name = "Clue Counter", description = "Counts clue scrolls solved", tags = {"clue","counter"})
public class ClueCounterPlugin extends Plugin {

	@Inject private ConfigManager configManager;
	@Inject private ClueCounterConfig config;

	enum Tier { EASY, MEDIUM, HARD, ELITE, MASTER }

	private final Map<Tier, Integer> counts = new EnumMap<>(Tier.class);

	private static final String CONFIG_GROUP = "cluecounter";

	@Provides
	ClueCounterConfig provideConfig(ConfigManager cm) {
		return cm.getConfig(ClueCounterConfig.class);
	}

	@Override
	protected void startUp() {
		for (Tier t : Tier.values()) {
			Integer saved = configManager.getConfiguration(CONFIG_GROUP, t.name().toLowerCase(), Integer.class);
			counts.put(t, saved != null ? saved : 0);
		}
	}

	@Override
	protected void shutDown() {
		persist();
	}

	@Subscribe
	public void onChatMessage(ChatMessage event) {
		if (event.getType() != ChatMessageType.GAMEMESSAGE) return;
		String msg = event.getMessage();
		Tier tier = parseTier(msg);
		if (tier == null) return;
		counts.merge(tier, 1, Integer::sum);
		configManager.setConfiguration(CONFIG_GROUP, tier.name().toLowerCase(), counts.get(tier));
	}

	private Tier parseTier(String msg) {
		String lower = msg.toLowerCase();
		if (!lower.contains("you have completed") || !lower.contains("clue scroll")) return null;
		if (lower.contains("easy")) return Tier.EASY;
		if (lower.contains("medium")) return Tier.MEDIUM;
		if (lower.contains("hard")) return Tier.HARD;
		if (lower.contains("elite")) return Tier.ELITE;
		if (lower.contains("master")) return Tier.MASTER;
		return null;
	}

	private void persist() {
		for (Tier t : Tier.values()) {
			configManager.setConfiguration(CONFIG_GROUP, t.name().toLowerCase(), counts.get(t));
		}
	}

	public Map<Tier, Integer> getCounts() {
		return counts;
	}
}
