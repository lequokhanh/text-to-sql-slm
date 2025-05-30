package com.slm.slmbackend.repository;

import com.slm.slmbackend.entity.ColumnRelation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface ColumnRelationRepository extends JpaRepository<ColumnRelation, Integer> {
}
