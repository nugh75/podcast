import streamlit as st
import edge_tts
import asyncio
import os
import tempfile
from pydub import AudioSegment
import shutil
import re
import traceback # Per loggare errori dettagliati

# --- Configurazione ---

# Lista di voci italiane disponibili in edge-tts
ITALIAN_VOICES = [
    "it-IT-ElsaNeural", "it-IT-IsabellaNeural", "it-IT-DiegoNeural", "it-IT-GianniNeural",
    "it-IT-BenignoNeural", "it-IT-CalimeroNeural", "it-IT-CataldoNeural", "it-IT-FabiolaNeural",
    "it-IT-FiammaNeural", "it-IT-GiuseppeNeural", "it-IT-LisandroNeural", "it-IT-PalmiraNeural",
    "it-IT-PierinaNeural", "it-IT-RinaldoNeural"
]

# Classificazione delle voci per genere
FEMALE_VOICES = ["it-IT-ElsaNeural", "it-IT-IsabellaNeural", "it-IT-FabiolaNeural", 
                "it-IT-FiammaNeural", "it-IT-PalmiraNeural", "it-IT-PierinaNeural"]

MALE_VOICES = ["it-IT-DiegoNeural", "it-IT-GianniNeural", "it-IT-BenignoNeural", 
              "it-IT-CalimeroNeural", "it-IT-CataldoNeural", "it-IT-GiuseppeNeural", 
              "it-IT-LisandroNeural", "it-IT-RinaldoNeural"]

# Silenzio da aggiungere tra i segmenti (in millisecondi)
SILENCE_BETWEEN_SEGMENTS_MS = 600

# --- Funzioni Ausiliarie ---

def sanitize_filename(name):
    """Rimuove caratteri non validi per i nomi dei file."""
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'[^\w_.-]', '', name) # Permette anche punti e trattini
    return name if name else "speaker"

async def generate_speech_segment(text, voice, output_file, fallback_voices=None):
    """
    Genera l'audio per un singolo segmento di testo usando edge-tts.
    Se la voce primaria fallisce, prova con voci alternative di fallback.
    """
    # Se non sono specificate voci di fallback, usa una lista predefinita
    if fallback_voices is None:
        # Voci che sappiamo funzionare bene
        if voice in FEMALE_VOICES:
            fallback_voices = ["it-IT-ElsaNeural", "it-IT-IsabellaNeural"]
        else:
            fallback_voices = ["it-IT-DiegoNeural", "it-IT-BenignoNeural"]
    
    # Rimuovi la voce primaria dalle voci di fallback se presente
    fallback_voices = [v for v in fallback_voices if v != voice]
    
    # Prima prova con la voce principale
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)
        # Verifica che il file sia stato creato e non sia vuoto
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            print(f"Segmento generato ({voice}): {output_file}")
            return output_file
        else:
            print(f"Attenzione: File {output_file} non generato correttamente o vuoto con voce {voice}.")
    except Exception as e:
        print(f"Errore durante la generazione TTS per '{text[:30]}...' con voce {voice}: {e}")
    
    # Se la voce principale fallisce, prova con le voci di fallback una alla volta
    for fallback_voice in fallback_voices:
        print(f"Tentativo con voce di fallback: {fallback_voice}")
        try:
            communicate = edge_tts.Communicate(text, fallback_voice)
            await communicate.save(output_file)
            # Verifica che il file sia stato creato e non sia vuoto
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                print(f"Segmento generato con voce di fallback ({fallback_voice}): {output_file}")
                return output_file
        except Exception as e:
            print(f"Anche la voce di fallback {fallback_voice} ha fallito: {e}")
    
    print(f"Tutte le voci hanno fallito per il segmento: '{text[:30]}...'")
    return None  # Indica fallimento completo

# --- Logica Principale Creazione Podcast (Asincrona) ---
# Questa funzione contiene la logica principale e sarà chiamata da Streamlit

def parse_script(script_text):
    """
    Analizza lo script e restituisce i segmenti e gli speaker unici.
    """
    parsed_segments = []
    lines = script_text.strip().splitlines()
    
    # Debug: stampa il numero di linee rilevate
    print(f"Linee totali nello script: {len(lines)}")
    
    for i, line in enumerate(lines):
        line = line.strip()
        if line:  # Verifica che la linea non sia vuota
            print(f"Analisi linea {i+1}: {line[:50]}...")
            
            if line.startswith("@"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    speaker_name = parts[0][1:].strip()
                    dialogue = parts[1].strip()
                    if speaker_name and dialogue:
                        parsed_segments.append({"speaker": speaker_name, "text": dialogue})
                        print(f"  ✓ Speaker rilevato: '{speaker_name}'")
                    else:
                        print(f"  ✗ Speaker o dialogo mancante: '{parts[0]}' / '{parts[1] if len(parts)>1 else ''}'")
                else:
                    print(f"  ✗ Formato non valido, manca il carattere ':' - {line}")
            else:
                print(f"  ✗ Non inizia con '@' - {line}")

    print(f"Segmenti totali analizzati: {len(parsed_segments)}")
    
    if not parsed_segments:
        raise ValueError("Nessun segmento di dialogo valido trovato. Assicurati che le linee inizino con '@NomeVoce: Testo'.")

    # Estrai gli speaker unici preservando l'ordine
    unique_speakers = list(dict.fromkeys([seg["speaker"] for seg in parsed_segments]))
    
    return parsed_segments, unique_speakers

def get_default_voice_for_speaker(speaker_name):
    """
    Cerca di determinare il genere dello speaker dal nome e assegna una voce appropriata.
    È un'euristica semplice basata su terminazioni comuni in italiano.
    """
    # Nomi che terminano con 'a' sono spesso femminili in italiano (con eccezioni)
    if speaker_name.lower().endswith(('a', 'ice', 'ina', 'essa')):
        return FEMALE_VOICES[hash(speaker_name) % len(FEMALE_VOICES)]
    else:
        return MALE_VOICES[hash(speaker_name) % len(MALE_VOICES)]

async def create_podcast_core_logic(script_text, voice_assignments=None):
    """
    Funzione asincrona che esegue la logica di parsing, generazione TTS e concatenazione.
    Restituisce il percorso del file MP3 finale o lancia un'eccezione.
    
    Parametri:
    - script_text: il testo dello script del podcast
    - voice_assignments: dizionario opzionale che mappa speaker a voci specifiche
    """
    # 1. Analisi Script
    parsed_segments, unique_speakers = parse_script(script_text)
    
    # 2. Assegnazione Voci
    if not ITALIAN_VOICES:
        raise ValueError("Nessuna voce italiana è stata definita nella configurazione.")
    
    # Se non ci sono assegnazioni di voci fornite, generane di nuove
    assigned_voices = {}
    if voice_assignments:
        assigned_voices = voice_assignments
    else:
        for speaker in unique_speakers:
            assigned_voices[speaker] = get_default_voice_for_speaker(speaker)
    
    print(f"Voci assegnate: {assigned_voices}")

    # 3. Generazione Segmenti Audio (in directory temporanea)
    # Usiamo una directory temporanea che Streamlit dovrebbe poter gestire/pulire
    temp_dir = tempfile.mkdtemp(prefix="podcast_streamlit_")
    print(f"Directory temporanea creata: {temp_dir}")
    segment_files_paths = []
    tasks = []

    try:
        for i, segment in enumerate(parsed_segments):
            speaker = segment["speaker"]
            sanitized_speaker = sanitize_filename(speaker)
            dialogue = segment["text"]
            voice = assigned_voices[speaker]
            output_filename = os.path.join(temp_dir, f"segment_{i:03d}_{sanitized_speaker}.mp3")
            tasks.append(generate_speech_segment(dialogue, voice, output_filename))

        results = await asyncio.gather(*tasks)
        valid_segment_files = [path for path in results if path is not None and os.path.exists(path)]

        if not valid_segment_files:
            raise RuntimeError("Errore: Nessun segmento audio è stato generato con successo. Controlla la connessione o il testo.")

        print(f"Segmenti audio generati con successo: {len(valid_segment_files)}/{len(parsed_segments)}")

        # 4. Concatenazione Segmenti
        combined_audio = AudioSegment.empty()
        silence = AudioSegment.silent(duration=SILENCE_BETWEEN_SEGMENTS_MS) if SILENCE_BETWEEN_SEGMENTS_MS > 0 else None

        for i, audio_file in enumerate(valid_segment_files):
            try:
                segment_audio = AudioSegment.from_mp3(audio_file)
                combined_audio += segment_audio
                if silence and i < len(valid_segment_files) - 1:
                    combined_audio += silence
            except Exception as e:
                print(f"Errore nel caricare o aggiungere il segmento {audio_file}: {e}. Segmento saltato.")

        if len(combined_audio) == 0:
            raise RuntimeError("Errore durante la combinazione dei segmenti audio. Il podcast finale è vuoto.")

        # 5. Esportazione File Finale
        final_podcast_file = os.path.join(temp_dir, "podcast_finale.mp3")
        combined_audio.export(final_podcast_file, format="mp3")
        print(f"Podcast finale esportato in: {final_podcast_file}")

        # 6. Restituisci il percorso del file finale
        # La pulizia della directory temporanea 'temp_dir' sarà gestita dal sistema operativo
        # o potrebbe richiedere meccanismi più avanzati in scenari di deploy complessi.
        return final_podcast_file

    except Exception as e:
        # In caso di errore durante la generazione/combinazione, puliamo la temp dir
        print(f"Errore durante la generazione, pulizia di {temp_dir}")
        if os.path.exists(temp_dir):
             try:
                 shutil.rmtree(temp_dir)
             except Exception as cleanup_error:
                 print(f"Errore durante la pulizia della directory temporanea {temp_dir}: {cleanup_error}")
        raise e # Rilancia l'eccezione originale

# --- Interfaccia Utente Streamlit ---

st.set_page_config(page_title="Generatore Podcast", page_icon="🎙️", layout="wide")

st.title("🎙️ Generatore di Podcast con Voci Italiane")
st.markdown("""
Inserisci uno script per il tuo podcast qui sotto.
Ogni riga di dialogo **deve** iniziare con `@NomeVoce:` (es. `@Marco:`).
L'applicazione assegnerà una voce italiana diversa (da Edge TTS) a ciascun 'NomeVoce' unico.
Premi **Genera Podcast** per creare il file audio MP3.
""")

st.info("ℹ️ Assicurati di aver installato `ffmpeg` sul tuo sistema affinché la combinazione audio funzioni correttamente.")

EXAMPLE_SCRIPT = """@Elsa: Ciao a tutti e benvenuti al nostro podcast settimanale!
@Diego: Ciao Elsa! Oggi abbiamo un argomento molto interessante.
@Elsa: Esatto Diego! Parleremo delle ultime novità nel campo dell'intelligenza artificiale generativa.
@Diego: Sembra affascinante. Cosa ne pensi dei recenti modelli di linguaggio?
@Elsa: Sono impressionanti, ma sollevano anche questioni etiche importanti. Non trovi?
@Diego: Assolutamente. L'etica nell'IA è fondamentale."""

# Area di testo per l'input dello script
script_text = st.text_area(
    "Script del Podcast:",
    height=350,
    placeholder="Incolla o scrivi qui il tuo script...\nRicorda: usa '@NomeVoce: Dialogo' per ogni battuta.",
    value=EXAMPLE_SCRIPT # Pre-compila con l'esempio
)

# Pulsante per analizzare lo script e trovare gli speaker
if st.button("📝 Analizza script e personalizza voci", type="secondary"):
    if not script_text or not script_text.strip():
        st.warning("Inserisci uno script prima di analizzarlo.", icon="⚠️")
    else:
        try:
            # Analizza lo script per trovare gli speaker
            parsed_segments, unique_speakers = parse_script(script_text)
            
            # Salva i dati nella sessione per l'uso successivo
            st.session_state['parsed_segments'] = parsed_segments
            st.session_state['unique_speakers'] = unique_speakers
            
            # Crea un dizionario con le assegnazioni predefinite
            if 'voice_assignments' not in st.session_state:
                st.session_state['voice_assignments'] = {
                    speaker: get_default_voice_for_speaker(speaker) 
                    for speaker in unique_speakers
                }
            
            st.success(f"✅ Rilevati {len(unique_speakers)} speaker: {', '.join(unique_speakers)}")
        except Exception as e:
            st.error(f"❌ Errore nell'analisi dello script: {e}", icon="🚨")

# Mostra le opzioni per la selezione delle voci se gli speaker sono stati rilevati
if 'unique_speakers' in st.session_state and st.session_state['unique_speakers']:
    st.subheader("Personalizzazione delle voci 🎤")
    st.markdown("Per ogni speaker, seleziona la voce che preferisci:")
    
    # Creiamo due colonne per speaker maschili e femminili
    col1, col2 = st.columns(2)
    
    # Possiamo mostrare informazioni sul genere delle voci
    col1.markdown("##### Speaker:")
    col2.markdown("##### Voce selezionata:")
    
    # Per ogni speaker permetti la selezione della voce
    for speaker in st.session_state['unique_speakers']:
        col1.write(f"**@{speaker}**")
        
        # Determina se il nome sembra femminile per suggerire voci appropriate
        default_is_female = any(speaker.lower().endswith(suffix) for suffix in ('a', 'ice', 'ina', 'essa'))
        default_voice_list = FEMALE_VOICES if default_is_female else MALE_VOICES
        
        # Determina la voce corrente selezionata
        current_voice = st.session_state['voice_assignments'].get(speaker, default_voice_list[0])
        
        # Crea un selettore per la voce di questo speaker
        selected_voice = col2.selectbox(
            f"Voce per {speaker}",
            options=ITALIAN_VOICES,
            index=ITALIAN_VOICES.index(current_voice) if current_voice in ITALIAN_VOICES else 0,
            key=f"voice_select_{speaker}",
            label_visibility="collapsed"
        )
        
        # Aggiorna l'assegnazione delle voci
        st.session_state['voice_assignments'][speaker] = selected_voice

# Pulsante per avviare la generazione
if st.button("🚀 Genera Podcast", type="primary"):
    if not script_text or not script_text.strip():
        st.warning("Inserisci uno script prima di generare il podcast.", icon="⚠️")
    else:
        # Mostra un messaggio di attesa mentre la funzione asincrona è in esecuzione
        with st.spinner("🎧 Generazione podcast in corso... Potrebbe richiedere alcuni istanti..."):
            try:
                # Usa le assegnazioni di voce personalizzate se disponibili
                voice_assignments = st.session_state.get('voice_assignments', None)
                
                # Esegui la funzione asincrona principale usando asyncio.run()
                # Questo bloccherà l'esecuzione di Streamlit finché l'async non termina
                final_podcast_path = asyncio.run(create_podcast_core_logic(
                    script_text, 
                    voice_assignments=voice_assignments
                ))

                # Verifica se il file è stato creato correttamente
                if final_podcast_path and os.path.exists(final_podcast_path):
                    st.success("✅ Podcast generato con successo!", icon="🎉")

                    # Mostra il player audio
                    st.audio(final_podcast_path, format='audio/mp3')

                    # Aggiungi un pulsante per il download
                    try:
                        with open(final_podcast_path, "rb") as fp:
                            st.download_button(
                                label="⬇️ Scarica Podcast (MP3)",
                                data=fp,
                                file_name="podcast_generato.mp3",
                                mime="audio/mp3"
                            )
                    except Exception as download_err:
                        st.error(f"Errore durante la preparazione del download: {download_err}")

                    # Informazione sulla gestione dei file temporanei
                    st.caption(f"Nota: Il file audio è stato salvato temporaneamente in: {os.path.dirname(final_podcast_path)}")

                else:
                    st.error("❌ La generazione del podcast non ha prodotto un file audio valido.", icon="🚨")

            except Exception as e:
                st.error(f"❌ Errore imprevisto durante la generazione del podcast:", icon="🚨")
                # Mostra l'errore dettagliato nell'app Streamlit
                st.exception(e)
                # Stampa anche nella console per il debug lato server
                print("--- ERRORE DETTAGLIATO ---")
                traceback.print_exc()
                print("--------------------------")

st.markdown("---")
st.markdown("Realizzato con ❤️ usando Streamlit, Edge-TTS e Pydub.")

# Nota sulla pulizia dei file temporanei:
# In questo script, ci affidiamo al sistema operativo per pulire le directory create da tempfile.mkdtemp().
# Per applicazioni web a lunga esecuzione o con molti utenti, potrebbe essere necessaria
# una strategia di pulizia più attiva (es. eliminare file più vecchi di X ore).