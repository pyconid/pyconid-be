from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models.Schedule import Schedule
from models.ScheduleType import ScheduleType
from models.Speaker import Speaker
from models.SpeakerSchedule import SpeakerSchedule
from models.User import User


def initial_speakers_seeders(db: Session, is_commit: bool = True):
    speakers = []
    for i in range(1, 11):
        user = User(
            username=f"speaker{i}",
            first_name="Speaker",
            last_name=f"{i}",
            email=f"speaker{i}@gmail.com",
        )
        db.add(user)
        db.flush()

        speaker = Speaker(user_id=user.id)
        db.add(speaker)
        speakers.append(speaker)

    if is_commit:
        db.commit()
    print(f"Inserted {len(speakers)} speakers.")


def initial_schedules_seeders(db: Session, is_commit: bool = True):
    speakers = db.query(Speaker.id).all()

    if not speakers:
        print("No speakers found in the database. Add speakers first.")
        return

    schedule_types = db.query(ScheduleType.id).all()
    schedule_type_id = schedule_types[0].id if schedule_types else None

    speaker_ids = [s.id for s in speakers]

    count = 0
    for i in range(1, 11):
        import random

        speaker_id = random.choice(speaker_ids)
        start_time = datetime.now() + timedelta(hours=i)
        end_time = start_time + timedelta(hours=1)

        schedule = Schedule(
            title=f"Topic {i}",
            schedule_type_id=schedule_type_id,
            description=f"Description for talk topic {i}.",
            start=start_time,
            end=end_time,
        )
        db.add(schedule)
        db.flush()

        junction = SpeakerSchedule(
            speaker_id=speaker_id,
            schedule_id=schedule.id,
            type="Main Speaker",
            order=1,
        )
        db.add(junction)
        count += 1

    if is_commit:
        db.commit()

    print(f"Inserted {count} schedules.")
