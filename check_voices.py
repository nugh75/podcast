import asyncio
import edge_tts

async def main():
    """Stampa tutte le voci italiane disponibili."""
    print("Verifica delle voci italiane disponibili in edge-tts...")
    
    try:
        voices = await edge_tts.list_voices()
        
        print("\nVoci italiane disponibili:")
        italian_voices = []
        
        for voice in voices:
            if voice["ShortName"].startswith("it-IT"):
                italian_voices.append(voice["ShortName"])
                gender = "Femminile" if voice["Gender"] == "Female" else "Maschile"
                print(f"- {voice['ShortName']} ({gender}): {voice['DisplayName']}")
        
        print(f"\nTotale voci italiane trovate: {len(italian_voices)}")
        
        # Genera una lista di codice Python per le voci
        print("\nCopia e incolla questo codice nel tuo file:")
        print("ITALIAN_VOICES = [")
        for i, voice in enumerate(italian_voices):
            if i < len(italian_voices) - 1:
                print(f'    "{voice}",')
            else:
                print(f'    "{voice}"')
        print("]")
        
        # Genera liste separate per voci maschili e femminili
        male_voices = []
        female_voices = []
        
        for voice in voices:
            if voice["ShortName"].startswith("it-IT"):
                if voice["Gender"] == "Female":
                    female_voices.append(voice["ShortName"])
                else:
                    male_voices.append(voice["ShortName"])
        
        print("\nFEMALE_VOICES = [")
        for i, voice in enumerate(female_voices):
            if i < len(female_voices) - 1:
                print(f'    "{voice}",')
            else:
                print(f'    "{voice}"')
        print("]")
        
        print("\nMALE_VOICES = [")
        for i, voice in enumerate(male_voices):
            if i < len(male_voices) - 1:
                print(f'    "{voice}",')
            else:
                print(f'    "{voice}"')
        print("]")
        
    except Exception as e:
        print(f"Errore durante il recupero delle voci: {e}")

if __name__ == "__main__":
    asyncio.run(main())
