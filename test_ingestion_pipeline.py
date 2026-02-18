#!/usr/bin/env python3
"""
Test script per la pipeline di preprocessing con input dall'Ingestion Layer

Questo script:
1. Carica un esempio di dati dal formato Ingestion Layer
2. Converte il formato in InputEmail
3. Esegue la pipeline di preprocessing completa
4. Mostra i risultati con dettagli su PII redatti e sezioni rimosse
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Union

# Aggiungi src al path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.models import InputEmail
from src.preprocessing import preprocess_email
from src.error_handling import preprocess_email_safe


def convert_ingestion_to_input_email(ingestion_data: Dict[str, Any]) -> InputEmail:
    """
    Converte il formato Ingestion Layer al formato InputEmail
    
    Args:
        ingestion_data: Dati nel formato dell'Ingestion Layer
        
    Returns:
        InputEmail instance
    """
    # Gestione del campo 'to' che può essere array o string
    to_addrs = ingestion_data.get("to", [])
    if isinstance(to_addrs, str):
        to_addrs = [addr.strip() for addr in to_addrs.split(",") if addr.strip()]
    elif not isinstance(to_addrs, list):
        to_addrs = [str(to_addrs)]
    
    # Conversione uid e uidvalidity da int a str
    uid = str(ingestion_data.get("uid", "0"))
    uidvalidity = str(ingestion_data.get("uidvalidity", "0"))
    
    # body_html_preview -> body_html
    body_html = ingestion_data.get("body_html_preview", "")
    
    # Calcolo flag body_truncated
    body_text = ingestion_data.get("body_text", "")
    body_truncated = len(body_text) >= 2000 or len(body_html) >= 500
    
    # Normalizza chiavi headers in lowercase (richiesto dalla pipeline)
    headers = {k.lower(): v for k, v in ingestion_data.get("headers", {}).items()}
    
    return InputEmail(
        uid=uid,
        uidvalidity=uidvalidity,
        mailbox=ingestion_data.get("mailbox", "INBOX"),
        from_addr=ingestion_data.get("from", "unknown@unknown.com"),
        to_addrs=to_addrs,
        subject=ingestion_data.get("subject", "(no subject)"),
        date=ingestion_data.get("date", ""),
        body_text=body_text,
        body_html=body_html,
        size=ingestion_data.get("size", 0),
        headers=headers,
        message_id=ingestion_data.get("message_id", ""),
        fetched_at=ingestion_data.get("fetched_at", ""),
        raw_bytes=None,  # Non disponibile in questo test
        body_truncated=body_truncated
    )


def print_processing_results(result: Any) -> None:
    """Stampa i risultati del preprocessing in modo leggibile"""
    
    print("\n" + "=" * 80)
    print("RISULTATI PREPROCESSING")
    print("=" * 80)
    
    if hasattr(result, 'error') and result.error:
        print(f"\n❌ ERRORE: {result.error}")
        print(f"Fallback applicato: {result.fallback_applied}")
        if result.result:
            print("\nRisultato parziale disponibile:")
            result = result.result
        else:
            return
    else:
        print("\n✅ Processing completato con successo")
    
    print(f"\n📧 IDENTIFICATORI:")
    print(f"  UID: {result.uid}")
    print(f"  Message-ID: {result.message_id}")
    print(f"  Mailbox: {result.mailbox}")
    print(f"  Size: {result.size} bytes")
    
    print(f"\n📨 HEADER (redatti):")
    print(f"  From: {result.from_addr_redacted}")
    print(f"  To: {', '.join(result.to_addrs_redacted)}")
    print(f"  Subject: {result.subject_canonical}")
    print(f"  Date: {result.date_parsed}")
    
    print(f"\n📝 BODY CANONICALIZZATO:")
    print(f"  Lunghezza: {len(result.body_text_canonical)} caratteri")
    print(f"  Hash originale: {result.body_original_hash[:16]}...")
    print(f"\n  Contenuto (primi 500 caratteri):")
    print(f"  {'-' * 76}")
    body_preview = result.body_text_canonical[:500]
    for line in body_preview.split('\n'):
        print(f"  {line}")
    if len(result.body_text_canonical) > 500:
        print(f"  ... (altri {len(result.body_text_canonical) - 500} caratteri)")
    print(f"  {'-' * 76}")
    
    print(f"\n🔒 PII REDATTI ({len(result.pii_entities)}):")
    if result.pii_entities:
        for pii in result.pii_entities:
            print(f"  - {pii.type}: hash={pii.original_hash[:8]}... → {pii.redacted}")
            print(f"    Posizione: {pii.span_start}-{pii.span_end}, Confidence: {pii.confidence:.2f}, Metodo: {pii.detection_method}")
    else:
        print("  Nessun PII rilevato")
    
    print(f"\n✂️  SEZIONI RIMOSSE ({len(result.removed_sections)}):")
    if result.removed_sections:
        for section in result.removed_sections:
            print(f"  - {section.type} (span: {section.span_start}-{section.span_end}, conf: {section.confidence:.2f})")
            print(f"    Preview: {section.content_preview[:60]}...")
    else:
        print("  Nessuna sezione rimossa")
    
    print(f"\n⏱️  PERFORMANCE:")
    print(f"  Durata processing: {result.processing_duration_ms} ms")
    print(f"  Timestamp: {result.processing_timestamp}")
    
    print(f"\n🔧 VERSIONING:")
    print(f"  Pipeline: {result.pipeline_version}")
    
    print("\n" + "=" * 80)


def main():
    """Main function"""
    
    # Path al file di test
    test_file = Path(__file__).parent / "test_ingestion_input.json"
    
    print(f"🔄 Caricamento dati da {test_file.name}...")
    
    try:
        with open(test_file, 'r', encoding='utf-8') as f:
            ingestion_data = json.load(f)
    except FileNotFoundError:
        print(f"❌ File non trovato: {test_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Errore nel parsing JSON: {e}")
        sys.exit(1)
    
    print("✅ Dati caricati correttamente")
    print(f"\n📊 DATI INGESTION LAYER:")
    print(f"  UID: {ingestion_data.get('uid')}")
    print(f"  From: {ingestion_data.get('from')}")
    print(f"  To: {ingestion_data.get('to')}")
    print(f"  Subject: {ingestion_data.get('subject')}")
    print(f"  Size: {ingestion_data.get('size')} bytes")
    print(f"  Body length: {len(ingestion_data.get('body_text', ''))} chars")
    
    # Conversione formato
    print("\n🔄 Conversione formato Ingestion Layer → InputEmail...")
    try:
        input_email = convert_ingestion_to_input_email(ingestion_data)
        print("✅ Conversione completata")
    except Exception as e:
        print(f"❌ Errore nella conversione: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Processing con modalità safe (con fallback)
    print("\n🔄 Avvio preprocessing pipeline (safe mode)...")
    try:
        result = preprocess_email_safe(input_email)
        print_processing_results(result)
        
        # Salva output
        output_file = Path(__file__).parent / "test_ingestion_output.json"
        print(f"\n💾 Salvando output in {output_file.name}...")
        
        # Converti result in dict per serializzazione JSON
        from dataclasses import asdict
        output_data = asdict(result)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"✅ Output salvato in {output_file}")
        
    except Exception as e:
        print(f"\n❌ ERRORE durante il processing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("\n✅ Test completato con successo!")


if __name__ == "__main__":
    main()
