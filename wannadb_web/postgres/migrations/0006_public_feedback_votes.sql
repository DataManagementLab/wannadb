LOCK TABLE public.document_feedback IN ACCESS EXCLUSIVE MODE;

-- Keep the latest vote when all copies agree. Conflicting directions cancel out.
-- NULL attribution can represent several deleted users and is kept separate.
WITH votes AS (
    SELECT documentid, userid, attribute, max(id) AS keep_id,
           count(DISTINCT positive) AS directions
    FROM public.document_feedback
    WHERE userid IS NOT NULL
    GROUP BY documentid, userid, attribute
)
DELETE FROM public.document_feedback AS feedback
USING votes
WHERE feedback.documentid = votes.documentid
  AND feedback.userid = votes.userid
  AND feedback.attribute = votes.attribute
  AND (votes.directions > 1 OR feedback.id <> votes.keep_id);

-- Statement-level checking also permits the existing atomic attribute-name swaps.
ALTER TABLE public.document_feedback
    ADD CONSTRAINT document_feedback_one_vote UNIQUE (documentid, userid, attribute)
    DEFERRABLE INITIALLY IMMEDIATE;
